"""PayPal checkout domain logic: create an intent + order, capture, webhook events.

Money safety rules (each one is covered by tests):
  * the amount charged is ALWAYS the server-side price; nothing from the client sets it
  * a capture only fulfils the intent when amount, currency and custom_id match exactly
  * capture/fulfil are idempotent, so the return page and the webhook can race safely
  * a buyer who already owns the title is NOT charged a second time
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import paypal
from app.billing.constants import SERIES_UNLOCK_PRICE_USD
from app.billing.fulfillment import fulfill_payment_intent
from app.billing.intent_helpers import validate_payment_amount
from app.billing.ownership import mark_succeeded_if_already_purchased
from app.billing.subscription_plans import resolve_active_plan
from app.config import get_settings
from app.core.apps import REELTIME
from app.core.exceptions import ConflictError, NotFoundError
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.series import Series
from app.models.user import User
from app.services.content_access import has_series_purchase, user_has_active_subscription
from app.services.telegram import commit_with_telegram, queue_telegram_alert

logger = logging.getLogger(__name__)

PAYPAL_METHOD = "paypal"
# The word shown in Purchase.bank / the Telegram alert.
PAYPAL_BANK_LABEL = "paypal"


def _ensure_configured() -> None:
    if not get_settings().paypal_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PayPal checkout is not available",
        )


async def _new_intent(
    db: AsyncSession,
    *,
    kind: str,
    amount: Decimal,
    order_id: str,
    user: User | None,
    guest_id: str | None,
    content_id: uuid.UUID | None = None,
    series_id: uuid.UUID | None = None,
    plan_code: str | None = None,
    plan_interval_days: int | None = None,
) -> PaymentIntent:
    intent = PaymentIntent(
        intent_id=f"pp-{uuid.uuid4().hex}",
        order_id=order_id,
        user_id=user.id if user else None,
        guest_id=None if user else guest_id,
        method=PAYPAL_METHOD,
        kind=kind,
        content_id=content_id,
        series_id=series_id,
        plan_code=plan_code,
        plan_interval_days=plan_interval_days,
        amount_usd=amount,
        status="pending",
    )
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return intent


async def _start_paypal_order(
    db: AsyncSession,
    intent: PaymentIntent,
    *,
    description: str,
    return_path: str | None,
    client: str,
    origin: str | None,
    card_first: bool = False,
) -> tuple[PaymentIntent, str]:
    """Create the PayPal order for a saved intent. On failure the intent is closed."""
    try:
        return_url, cancel_url = paypal.build_return_urls(
            intent.intent_id, return_path, client, origin
        )
        order = await paypal.create_order(
            intent_id=intent.intent_id,
            order_id=intent.order_id,
            amount_usd=intent.amount_usd,
            description=description,
            return_url=return_url,
            cancel_url=cancel_url,
            card_first=card_first,
        )
        link = paypal.approve_url(order)
        if not order.get("id") or not link:
            raise paypal.PaypalApiError(502, "BAD_RESPONSE", "No order id / approval link")
    except paypal.PaypalNotConfiguredError as exc:
        await _close_intent(db, intent, "failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PayPal checkout is not available",
        ) from exc
    except (paypal.PaypalApiError, httpx.HTTPError) as exc:
        logger.error("PayPal order creation failed for %s: %s", intent.intent_id, exc)
        await _close_intent(db, intent, "failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start PayPal checkout. Please try again.",
        ) from exc

    intent.paypal_order_id = str(order["id"])
    await db.commit()
    await db.refresh(intent)
    return intent, link


async def _close_intent(db: AsyncSession, intent: PaymentIntent, new_status: str) -> None:
    intent.status = new_status
    intent.resolved_at = datetime.now(UTC)
    await db.commit()


async def create_movie_paypal_intent(
    db: AsyncSession,
    *,
    content_id: uuid.UUID,
    user: User | None,
    guest_id: str | None,
    return_path: str | None,
    client: str,
    origin: str | None,
    card_first: bool = False,
) -> tuple[PaymentIntent, str]:
    _ensure_configured()
    owner = Purchase.user_id == user.id if user is not None else Purchase.guest_id == guest_id
    existing = await db.execute(
        select(Purchase.id).where(owner, Purchase.content_id == content_id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("Movie already purchased")

    result = await db.execute(
        select(Content).where(
            Content.id == content_id,
            Content.type == "single",
            # TV5 titles come with a TV5 plan and are never sold one by one.
            Content.app == REELTIME,
            Content.is_published.is_(True),
        )
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")

    intent = await _new_intent(
        db,
        kind="single",
        amount=validate_payment_amount(movie.price_usd),
        order_id=f"movie-{uuid.uuid4().hex}",
        user=user,
        guest_id=guest_id,
        content_id=movie.id,
    )
    return await _start_paypal_order(
        db,
        intent,
        description=f"REELTIME - {movie.title}",
        return_path=return_path,
        client=client,
        origin=origin,
        card_first=card_first,
    )


async def create_series_paypal_intent(
    db: AsyncSession,
    *,
    series: Series,
    user: User | None,
    guest_id: str | None,
    return_path: str | None,
    client: str,
    origin: str | None,
    card_first: bool = False,
) -> tuple[PaymentIntent, str]:
    _ensure_configured()
    if series.app != REELTIME:
        raise NotFoundError("Series not found")
    if user and await user_has_active_subscription(db, user.id):
        raise ConflictError("You already have an active subscription")
    if await has_series_purchase(
        db, series.id, user_id=user.id if user else None, guest_id=guest_id
    ):
        raise ConflictError("Series already unlocked")

    intent = await _new_intent(
        db,
        kind="series",
        amount=validate_payment_amount(SERIES_UNLOCK_PRICE_USD),
        order_id=f"series-{uuid.uuid4().hex}",
        user=user,
        guest_id=guest_id,
        series_id=series.id,
    )
    return await _start_paypal_order(
        db,
        intent,
        description=f"REELTIME - {series.title}",
        return_path=return_path,
        client=client,
        origin=origin,
        card_first=card_first,
    )


async def create_subscription_paypal_intent(
    db: AsyncSession,
    *,
    user: User,
    plan_code: str | None,
    return_path: str | None,
    client: str,
    origin: str | None,
    card_first: bool = False,
) -> tuple[PaymentIntent, str]:
    _ensure_configured()
    plan = await resolve_active_plan(db, plan_code)
    intent = await _new_intent(
        db,
        kind="sub",
        amount=validate_payment_amount(plan.price_usd),
        # Fulfilment re-reads the plan from this shape (see _plan_code_from_order_id).
        order_id=f"sub-{plan.code}-{uuid.uuid4().hex}",
        user=user,
        guest_id=None,
        plan_code=plan.code,
        plan_interval_days=plan.billing_interval_days,
    )
    return await _start_paypal_order(
        db,
        intent,
        description=f"{'REELTIME' if plan.app == REELTIME else 'TV5'} - {plan.name}",
        return_path=return_path,
        client=client,
        origin=origin,
        card_first=card_first,
    )


async def _intent_by_paypal_order(db: AsyncSession, paypal_order_id: str) -> PaymentIntent:
    result = await db.execute(
        select(PaymentIntent).where(PaymentIntent.paypal_order_id == paypal_order_id)
    )
    intent = result.scalar_one_or_none()
    if intent is None:
        raise NotFoundError("Payment not found")
    return intent


async def _alert(db: AsyncSession, text: str) -> None:
    queue_telegram_alert(db, text)
    await commit_with_telegram(db)


async def _apply_capture(
    db: AsyncSession, intent: PaymentIntent, order: dict[str, Any]
) -> PaymentIntent:
    """Turn PayPal's capture result into intent state (fulfil / keep pending / fail)."""
    capture = paypal.first_capture(order)
    if capture is None:
        # Approved but not captured (or capture still being created).
        raise ConflictError("PayPal has not completed this payment yet")

    capture_status = str(capture.get("status") or "").upper()
    capture_id = str(capture.get("id") or "") or None

    if capture_status == "COMPLETED":
        if not paypal.capture_matches(
            capture, intent_id=intent.intent_id, amount_usd=intent.amount_usd
        ):
            logger.error("PayPal capture does not match intent %s", intent.intent_id)
            intent.paypal_capture_id = capture_id
            intent.status = "failed"
            intent.resolved_at = datetime.now(UTC)
            await _alert(
                db,
                "PayPal capture MISMATCH - access NOT granted, check PayPal dashboard\n"
                f"- Intent: {intent.intent_id}\n"
                f"- Expected: {intent.amount_usd} USD\n"
                f"- Capture: {capture_id}",
            )
            await db.refresh(intent)
            return intent
        intent.paypal_capture_id = capture_id
        # Persist the capture id before fulfil re-reads the row under a lock.
        await db.flush()
        await fulfill_payment_intent(db, intent, bank=PAYPAL_BANK_LABEL)
        await commit_with_telegram(db)
        await db.refresh(intent)
        return intent

    if capture_status == "PENDING":
        # E.g. fraud/eCheck review: the webhook (PAYMENT.CAPTURE.COMPLETED) fulfils later.
        intent.paypal_capture_id = capture_id
        await db.commit()
        await db.refresh(intent)
        return intent

    logger.warning("PayPal capture %s ended as %s", capture_id, capture_status)
    intent.paypal_capture_id = capture_id
    await _close_intent(db, intent, "failed")
    await db.refresh(intent)
    return intent


async def capture_paypal_order(db: AsyncSession, paypal_order_id: str) -> PaymentIntent:
    """Capture an approved PayPal order and unlock the purchase. Safe to call twice."""
    _ensure_configured()
    intent = await _intent_by_paypal_order(db, paypal_order_id)

    if intent.status in ("succeeded", "superseded"):
        return intent
    if intent.status != "pending":
        raise ConflictError("This payment is no longer open")

    # Already owned through another receipt: do not take a second payment.
    if await mark_succeeded_if_already_purchased(db, intent):
        await commit_with_telegram(db)
        await db.refresh(intent)
        return intent

    try:
        order = await paypal.capture_order(paypal_order_id, intent_id=intent.intent_id)
    except paypal.PaypalApiError as exc:
        if exc.issue == "ORDER_ALREADY_CAPTURED":
            order = await _get_order_or_502(paypal_order_id)
        elif exc.issue == "ORDER_NOT_APPROVED":
            raise ConflictError("The PayPal payment was not approved") from exc
        elif exc.issue in ("INSTRUMENT_DECLINED", "PAYER_ACTION_REQUIRED"):
            raise ConflictError(
                "PayPal could not use that payment method. Please try again with another one."
            ) from exc
        elif exc.status_code == 404:
            raise NotFoundError("Payment not found") from exc
        else:
            logger.error("PayPal capture failed for %s: %s", intent.intent_id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="PayPal could not confirm this payment. Please try again shortly.",
            ) from exc
    except httpx.HTTPError as exc:
        logger.error("PayPal capture request failed for %s: %s", intent.intent_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal could not confirm this payment. Please try again shortly.",
        ) from exc

    return await _apply_capture(db, intent, order)


async def _get_order_or_502(paypal_order_id: str) -> dict[str, Any]:
    try:
        return await paypal.get_order(paypal_order_id)
    except (paypal.PaypalApiError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal could not confirm this payment. Please try again shortly.",
        ) from exc


# --- webhook events ---------------------------------------------------------------


def _resource(event: dict[str, Any]) -> dict[str, Any]:
    resource = event.get("resource")
    return resource if isinstance(resource, dict) else {}


def _order_id_of_capture(resource: dict[str, Any]) -> str | None:
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    value = related.get("order_id")
    return str(value) if value else None


async def _intent_for_capture_event(
    db: AsyncSession, resource: dict[str, Any]
) -> PaymentIntent | None:
    custom_id = resource.get("custom_id")
    if isinstance(custom_id, str) and custom_id:
        result = await db.execute(select(PaymentIntent).where(PaymentIntent.intent_id == custom_id))
        found = result.scalar_one_or_none()
        if found is not None and found.method == PAYPAL_METHOD:
            return found
    order_id = _order_id_of_capture(resource)
    if order_id:
        result = await db.execute(
            select(PaymentIntent).where(PaymentIntent.paypal_order_id == order_id)
        )
        return result.scalar_one_or_none()
    return None


async def process_paypal_event(db: AsyncSession, event: dict[str, Any]) -> str:
    """Handle one VERIFIED webhook event. Returns a short outcome label for the log."""
    event_type = str(event.get("event_type") or "")
    resource = _resource(event)

    if event_type == "CHECKOUT.ORDER.APPROVED":
        order_id = str(resource.get("id") or "")
        if not order_id:
            return "ignored: no order id"
        try:
            intent = await capture_paypal_order(db, order_id)
        except NotFoundError:
            return "ignored: unknown order"
        except ConflictError as exc:
            return f"not captured: {exc.detail}"
        return f"capture -> {intent.status}"

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        intent = await _intent_for_capture_event(db, resource)
        if intent is None:
            return "ignored: unknown intent"
        if intent.status in ("succeeded", "superseded"):
            return "already fulfilled"
        if intent.status != "pending":
            return f"ignored: intent is {intent.status}"
        if not paypal.capture_matches(
            resource, intent_id=intent.intent_id, amount_usd=intent.amount_usd
        ):
            await _alert(
                db,
                "PayPal webhook amount MISMATCH - access NOT granted\n"
                f"- Intent: {intent.intent_id}\n- Capture: {resource.get('id')}",
            )
            return "mismatch"
        intent.paypal_capture_id = str(resource.get("id") or "") or None
        await db.flush()
        await fulfill_payment_intent(db, intent, bank=PAYPAL_BANK_LABEL)
        await commit_with_telegram(db)
        return "fulfilled"

    if event_type in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED"):
        intent = await _intent_for_capture_event(db, resource)
        if intent is not None and intent.status == "pending":
            await _close_intent(db, intent, "failed")
            return "marked failed"
        return "ignored"

    if event_type in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        intent = await _intent_for_capture_event(db, resource)
        ref = intent.intent_id if intent else resource.get("id")
        # Access is NOT revoked automatically: a human decides (partial refunds, goodwill).
        await _alert(
            db,
            f"PayPal {event_type.rsplit('.', 1)[-1].lower()} - review access manually\n"
            f"- Intent: {ref}\n"
            f"- Amount: {(resource.get('amount') or {}).get('value')} "
            f"{(resource.get('amount') or {}).get('currency_code')}",
        )
        return "alerted"

    return f"ignored: {event_type or 'no type'}"
