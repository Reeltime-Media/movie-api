"""HTTP routes for PayPal: ``/payments/paypal/*`` (buyer) and ``/webhooks/paypal`` (PayPal)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.billing import paypal
from app.billing.intent_helpers import read_payment_intent
from app.billing.paypal_intents import (
    capture_paypal_order,
    create_movie_paypal_intent,
    create_series_paypal_intent,
    create_subscription_paypal_intent,
    process_paypal_event,
)
from app.billing.schemas import (
    PaymentIntentRead,
    PaypalCaptureRequest,
    PaypalIntentCreate,
    PaypalIntentRead,
)
from app.config import get_settings
from app.core.guest import get_or_create_guest_id
from app.dependencies import CurrentUser, DBSession, OptionalUser
from app.models.webhook_event import WebhookEvent
from app.rate_limit import limiter
from app.services.series import get_series_or_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments/paypal", tags=["payments"])
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_MAX_WEBHOOK_BYTES = 256 * 1024


def _read(intent, approve_url: str) -> PaypalIntentRead:
    return PaypalIntentRead(
        intent_id=intent.intent_id,
        order_id=intent.order_id,
        approve_url=approve_url,
        amount_usd=intent.amount_usd,
        status=intent.status,
        created_at=intent.created_at,
    )


@router.post(
    "/movies/{content_id}/intent",
    response_model=PaypalIntentRead,
    status_code=201,
)
@limiter.limit("8/minute")
async def create_movie_intent(
    content_id: uuid.UUID,
    data: PaypalIntentCreate,
    db: DBSession,
    request: Request,
    response: Response,
    user: OptionalUser,
):
    """Start a PayPal checkout for one movie (user or guest). The client then sends the
    buyer to ``approve_url``; PayPal returns them to our /pay/paypal/return page."""
    guest_id = None if user else get_or_create_guest_id(request, response)
    intent, url = await create_movie_paypal_intent(
        db,
        content_id=content_id,
        user=user,
        guest_id=guest_id,
        return_path=data.return_path,
        client=data.client,
        origin=data.return_origin,
    )
    return _read(intent, url)


@router.post(
    "/series/{slug}/unlock-intent",
    response_model=PaypalIntentRead,
    status_code=201,
)
@limiter.limit("8/minute")
async def create_series_intent(
    slug: str,
    data: PaypalIntentCreate,
    db: DBSession,
    request: Request,
    response: Response,
    user: OptionalUser,
):
    series = await get_series_or_404(db, slug, published_only=True)
    guest_id = None if user else get_or_create_guest_id(request, response)
    intent, url = await create_series_paypal_intent(
        db,
        series=series,
        user=user,
        guest_id=guest_id,
        return_path=data.return_path,
        client=data.client,
        origin=data.return_origin,
    )
    return _read(intent, url)


@router.post(
    "/subscription-intent",
    response_model=PaypalIntentRead,
    status_code=201,
)
@limiter.limit("8/minute")
async def create_subscription_intent(
    data: PaypalIntentCreate,
    db: DBSession,
    request: Request,
    current_user: CurrentUser,
    plan_code: str | None = None,
):
    _ = request  # SlowAPI needs Request on limited routes
    intent, url = await create_subscription_paypal_intent(
        db,
        user=current_user,
        plan_code=plan_code,
        return_path=data.return_path,
        client=data.client,
        origin=data.return_origin,
    )
    return _read(intent, url)


@router.post("/capture", response_model=PaymentIntentRead)
@limiter.limit("30/minute")
async def capture_order(
    data: PaypalCaptureRequest,
    db: DBSession,
    request: Request,
):
    """Finish a payment the buyer just approved on PayPal.

    Deliberately not tied to a login: the in-app browser that PayPal returns to on mobile
    has no session. That is safe because the PayPal order id is an unguessable token bound
    to one intent, the amount is the server-side price, and capturing only ever pays US
    (access always goes to the buyer who created the intent). Repeating it is harmless.
    """
    _ = request
    intent = await capture_paypal_order(db, data.order_id)
    return read_payment_intent(intent)


def _clean_event(event: dict[str, Any]) -> dict[str, Any]:
    """Keep what is needed to audit a webhook; drop payer details (names, emails)."""
    resource = event.get("resource") if isinstance(event.get("resource"), dict) else {}
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    return {
        "id": event.get("id"),
        "event_type": event.get("event_type"),
        "create_time": event.get("create_time"),
        "resource_type": event.get("resource_type"),
        "summary": event.get("summary"),
        "resource": {
            "id": resource.get("id"),
            "status": resource.get("status"),
            "custom_id": resource.get("custom_id"),
            "invoice_id": resource.get("invoice_id"),
            "amount": resource.get("amount"),
            "order_id": related.get("order_id"),
        },
    }


@webhook_router.post("/paypal")
@limiter.limit("300/minute")
async def paypal_webhook(request: Request, db: DBSession):
    """PayPal -> us. Nothing is trusted until PayPal itself confirms the signature."""
    settings = get_settings()
    if not (settings.paypal_enabled and settings.paypal_webhook_id.strip()):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PayPal webhooks are not configured",
        )

    body = await request.body()
    if len(body) > _MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON") from exc
    if not isinstance(event, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")

    headers = {key.lower(): value for key, value in request.headers.items()}
    if not await paypal.verify_webhook_signature(headers, event):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature"
        )

    event_id = str(event.get("id") or "")
    if event_id:
        seen = await db.execute(
            select(WebhookEvent.id)
            .where(
                WebhookEvent.provider == "paypal",
                WebhookEvent.payload["id"].astext == event_id,
                WebhookEvent.processed_at.is_not(None),
            )
            .limit(1)
        )
        if seen.scalar_one_or_none() is not None:
            return {"status": "duplicate"}

    record = WebhookEvent(
        provider="paypal",
        payload=_clean_event(event),
        received_at=datetime.now(UTC),
    )
    db.add(record)
    await db.flush()

    # An error here (e.g. PayPal/DB briefly down) bubbles up as 5xx: PayPal retries the
    # delivery later, and the unprocessed record is rolled back with the request.
    outcome = await process_paypal_event(db, event)
    record.processed_at = datetime.now(UTC)
    await db.commit()
    logger.info("PayPal webhook %s %s -> %s", event_id, event.get("event_type"), outcome)
    return {"status": "ok"}
