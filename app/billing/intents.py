"""Bakong payment-intent create / reuse / poll settle (domain logic)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import bakong
from app.billing.bakong_settle import (
    bakong_qr_confirmed_unpaid,
    qr_is_stale,
    settle_bakong_intent_if_paid,
)
from app.billing.constants import SERIES_UNLOCK_PRICE_USD
from app.billing.intent_helpers import regenerate_bakong_qr, validate_payment_amount
from app.billing.ownership import mark_succeeded_if_already_purchased
from app.billing.subscription_plans import resolve_active_plan
from app.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.series import Series
from app.models.user import User
from app.services.content_access import has_series_purchase, user_has_active_subscription
from app.services.telegram import commit_with_telegram

logger = logging.getLogger(__name__)


def _identity_filter(user: User | None, guest_id: str | None):
    if user:
        return PaymentIntent.user_id == user.id
    return PaymentIntent.guest_id == guest_id


def _purchase_filter(user: User | None, guest_id: str | None):
    if user:
        return Purchase.user_id == user.id
    return Purchase.guest_id == guest_id


async def _lock_buyer(db: AsyncSession, user: User | None) -> None:
    """Serialize first pending-intent creation per logged-in buyer."""
    if user is None:
        return
    await db.execute(select(User).where(User.id == user.id).with_for_update())


async def _reuse_or_refresh_pending(
    db: AsyncSession,
    pending_intent: PaymentIntent,
    *,
    check_ownership: bool = True,
) -> PaymentIntent:
    """Shared pending-QR path: reuse fresh, settle/regenerate when stale."""
    if not qr_is_stale(pending_intent):
        if check_ownership and await mark_succeeded_if_already_purchased(db, pending_intent):
            await commit_with_telegram(db)
            await db.refresh(pending_intent)
        return pending_intent

    if await settle_bakong_intent_if_paid(db, pending_intent):
        await commit_with_telegram(db)
        await db.refresh(pending_intent)
        return pending_intent

    if check_ownership and await mark_succeeded_if_already_purchased(db, pending_intent):
        await commit_with_telegram(db)
        await db.refresh(pending_intent)
        return pending_intent

    if await bakong_qr_confirmed_unpaid(pending_intent):
        await regenerate_bakong_qr(pending_intent)
        await commit_with_telegram(db)
        await db.refresh(pending_intent)
    return pending_intent


async def _commit_new_intent_or_reuse(
    db: AsyncSession,
    intent: PaymentIntent,
    *,
    pending_lookup,
    check_ownership: bool = True,
) -> PaymentIntent:
    """Commit a newly built pending intent; on unique conflict, return the winner."""
    db.add(intent)
    try:
        await commit_with_telegram(db)
    except IntegrityError:
        await db.rollback()
        db.info.pop("pending_telegram_alerts", None)
        logger.info(
            "Concurrent pending checkout — reusing existing intent kind=%s",
            intent.kind,
        )
        result = await db.execute(pending_lookup)
        existing = result.scalars().first()
        if existing is None:
            raise
        return await _reuse_or_refresh_pending(
            db, existing, check_ownership=check_ownership
        )
    await db.refresh(intent)
    return intent


async def create_or_reuse_movie_bakong_intent(
    db: AsyncSession,
    *,
    content_id: UUID,
    user: User | None,
    guest_id: str | None,
) -> PaymentIntent:
    """Inline KHQR checkout for a single movie (user or guest)."""
    identity_filter = _identity_filter(user, guest_id)
    purchase_filter = _purchase_filter(user, guest_id)

    existing_purchase = await db.execute(
        select(Purchase.id)
        .where(purchase_filter, Purchase.content_id == content_id)
        .limit(1)
    )
    if existing_purchase.scalar_one_or_none() is not None:
        raise ConflictError("Movie already purchased")

    await _lock_buyer(db, user)

    pending_lookup = (
        select(PaymentIntent)
        .where(
            identity_filter,
            PaymentIntent.method == "bakong",
            PaymentIntent.kind == "single",
            PaymentIntent.content_id == content_id,
            PaymentIntent.status == "pending",
        )
        .order_by(PaymentIntent.created_at.asc())
    )
    pending = await db.execute(pending_lookup.with_for_update())
    pending_intent = pending.scalars().first()
    if pending_intent:
        return await _reuse_or_refresh_pending(db, pending_intent)

    result = await db.execute(
        select(Content).where(
            Content.id == content_id,
            Content.type == "single",
            Content.is_published.is_(True),
        )
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")

    amount = validate_payment_amount(movie.price_usd)
    order_id = f"movie-{uuid.uuid4().hex}"
    bill_number = uuid.uuid4().hex[:20]
    qr_string, md5, merchant_name = await bakong.generate_khqr(amount, bill_number)
    now = datetime.now(UTC)

    intent = PaymentIntent(
        intent_id=f"bkg-{uuid.uuid4().hex}",
        order_id=order_id,
        user_id=user.id if user else None,
        guest_id=guest_id,
        method="bakong",
        bakong_md5=md5,
        bakong_qr=qr_string,
        bakong_merchant_name=merchant_name or get_settings().bakong_merchant_name or None,
        bakong_qr_created_at=now,
        kind="single",
        content_id=movie.id,
        amount_usd=amount,
        status="pending",
    )
    return await _commit_new_intent_or_reuse(
        db, intent, pending_lookup=pending_lookup
    )


async def create_or_reuse_series_bakong_intent(
    db: AsyncSession,
    *,
    series: Series,
    user: User | None,
    guest_id: str | None,
) -> PaymentIntent:
    """One-time series unlock KHQR (same guest/user flow as movies)."""
    identity_filter = _identity_filter(user, guest_id)

    if user and await user_has_active_subscription(db, user.id):
        raise ConflictError("You already have an active subscription")

    if await has_series_purchase(
        db,
        series.id,
        user_id=user.id if user else None,
        guest_id=guest_id,
    ):
        raise ConflictError("Series already unlocked")

    await _lock_buyer(db, user)

    pending_lookup = (
        select(PaymentIntent)
        .where(
            identity_filter,
            PaymentIntent.method == "bakong",
            PaymentIntent.kind == "series",
            PaymentIntent.series_id == series.id,
            PaymentIntent.status == "pending",
        )
        .order_by(PaymentIntent.created_at.asc())
    )
    pending = await db.execute(pending_lookup.with_for_update())
    pending_intent = pending.scalars().first()
    if pending_intent:
        return await _reuse_or_refresh_pending(db, pending_intent)

    amount = validate_payment_amount(SERIES_UNLOCK_PRICE_USD)
    order_id = f"series-{uuid.uuid4().hex}"
    bill_number = uuid.uuid4().hex[:20]
    qr_string, md5, merchant_name = await bakong.generate_khqr(amount, bill_number)
    now = datetime.now(UTC)

    intent = PaymentIntent(
        intent_id=f"bkg-{uuid.uuid4().hex}",
        order_id=order_id,
        user_id=user.id if user else None,
        guest_id=guest_id,
        method="bakong",
        bakong_md5=md5,
        bakong_qr=qr_string,
        bakong_merchant_name=merchant_name or get_settings().bakong_merchant_name or None,
        bakong_qr_created_at=now,
        kind="series",
        series_id=series.id,
        amount_usd=amount,
        status="pending",
    )
    return await _commit_new_intent_or_reuse(
        db, intent, pending_lookup=pending_lookup
    )


async def create_or_reuse_subscription_bakong_intent(
    db: AsyncSession,
    *,
    user: User,
    plan_code: str | None = None,
) -> PaymentIntent:
    """Subscription plan KHQR — scoped by plan_code (amount fallback for legacy rows)."""
    plan = await resolve_active_plan(db, plan_code)
    amount = validate_payment_amount(plan.price_usd)

    await _lock_buyer(db, user)

    pending_lookup = (
        select(PaymentIntent)
        .where(
            PaymentIntent.user_id == user.id,
            PaymentIntent.method == "bakong",
            PaymentIntent.kind == "sub",
            PaymentIntent.status == "pending",
            or_(
                PaymentIntent.plan_code == plan.code,
                and_(
                    PaymentIntent.plan_code.is_(None),
                    PaymentIntent.amount_usd == amount,
                ),
            ),
        )
        .order_by(PaymentIntent.created_at.asc())
    )
    pending = await db.execute(pending_lookup.with_for_update())
    pending_intent = pending.scalars().first()
    if pending_intent:
        # Subs don't use ownership unstick (no per-title purchase).
        return await _reuse_or_refresh_pending(db, pending_intent, check_ownership=False)

    order_id = f"sub-{plan.code}-{uuid.uuid4().hex}"
    bill_number = uuid.uuid4().hex[:20]
    qr_string, md5, merchant_name = await bakong.generate_khqr(amount, bill_number)
    now = datetime.now(UTC)

    intent = PaymentIntent(
        intent_id=f"bkg-{uuid.uuid4().hex}",
        order_id=order_id,
        user_id=user.id,
        method="bakong",
        bakong_md5=md5,
        bakong_qr=qr_string,
        bakong_merchant_name=merchant_name or get_settings().bakong_merchant_name or None,
        bakong_qr_created_at=now,
        kind="sub",
        content_id=None,
        plan_code=plan.code,
        plan_interval_days=plan.billing_interval_days,
        amount_usd=amount,
        status="pending",
    )
    return await _commit_new_intent_or_reuse(
        db, intent, pending_lookup=pending_lookup, check_ownership=False
    )


async def load_buyer_intent(
    db: AsyncSession,
    *,
    intent_id: str,
    user: User | None,
    guest_id: str | None,
) -> PaymentIntent:
    if user:
        identity_filter = PaymentIntent.user_id == user.id
    else:
        if not guest_id:
            raise NotFoundError("Payment intent not found")
        identity_filter = PaymentIntent.guest_id == guest_id
    result = await db.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == intent_id, identity_filter)
    )
    intent = result.scalar_one_or_none()
    if not intent:
        raise NotFoundError("Payment intent not found")
    return intent


async def settle_pending_intent_on_poll(
    db: AsyncSession,
    intent: PaymentIntent,
) -> PaymentIntent:
    """NBC/ownership settle path used by GET /payments/intents/{id}."""
    from app.billing.bakong_settle import nbc_settle_enabled

    if intent.method != "bakong" or intent.status != "pending":
        return intent

    if await mark_succeeded_if_already_purchased(db, intent):
        await commit_with_telegram(db)
        await db.refresh(intent)
        return intent

    if not (nbc_settle_enabled() and intent.bakong_md5):
        return intent

    from app.billing.bakong_check_cache import mark_intent_polled
    from app.billing.bakong_quota import bakong_checks_blocked

    if bakong_checks_blocked():
        mark_intent_polled(intent.intent_id)
        return intent

    if await settle_bakong_intent_if_paid(db, intent):
        await commit_with_telegram(db)
        await db.refresh(intent)
    elif intent.content_id is not None:
        identity = (
            (PaymentIntent.user_id == intent.user_id)
            if intent.user_id is not None
            else (PaymentIntent.guest_id == intent.guest_id)
        )
        siblings = await db.execute(
            select(PaymentIntent)
            .where(
                identity,
                PaymentIntent.method == "bakong",
                PaymentIntent.kind == "single",
                PaymentIntent.content_id == intent.content_id,
                PaymentIntent.status == "pending",
                PaymentIntent.intent_id != intent.intent_id,
                PaymentIntent.bakong_md5.is_not(None),
            )
            .order_by(PaymentIntent.created_at.desc())
            .limit(1)
        )
        sibling = siblings.scalars().first()
        if sibling and await settle_bakong_intent_if_paid(db, sibling):
            # Sibling was the paid receipt; this intent did not collect money.
            from app.billing.ownership import STATUS_SUPERSEDED

            intent.status = STATUS_SUPERSEDED
            intent.resolved_at = sibling.resolved_at
            await commit_with_telegram(db)
            await db.refresh(intent)
    mark_intent_polled(intent.intent_id)
    return intent
