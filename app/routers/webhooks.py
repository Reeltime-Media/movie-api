import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.core.webhook_auth import verify_baray_webhook
from app.dependencies import DBSession
from app.models.payment_intent import PaymentIntent
from app.models.webhook_event import WebhookEvent
from app.rate_limit import limiter
from app.billing.fulfillment import fulfill_payment_intent
from app.billing.payment import decrypt_order_id

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Mounted only when BARAY_ENABLED=true. Handler below still 503s until Baray
# settle path is fully re-verified (idempotent event ids, etc.).


@router.post("/baray")
@limiter.limit("120/minute")
async def baray_webhook(request: Request, db: DBSession):
    # BARAY DISABLED — reject if somehow mounted again before re-enable.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Baray webhooks are disabled",
    )
    body = await verify_baray_webhook(request)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload"
        )

    encrypted_order_id = payload.get("encrypted_order_id")
    if not isinstance(encrypted_order_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing encrypted_order_id",
        )

    try:
        order_id = decrypt_order_id(encrypted_order_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted_order_id",
        ) from exc

    event = WebhookEvent(
        provider="baray",
        payload=payload,
        received_at=datetime.now(UTC),
    )
    db.add(event)
    await db.flush()

    try:
        await _process_baray_event(db, order_id, payload)
        event.processed_at = datetime.now(UTC)
    except Exception as exc:
        event.error = str(exc)

    await db.commit()
    return {"status": "ok"}


async def _process_baray_event(db, order_id: str, payload: dict) -> None:
    result = await db.execute(select(PaymentIntent).where(PaymentIntent.order_id == order_id))
    intent = result.scalar_one_or_none()
    if not intent:
        return

    bank = payload.get("bank") if isinstance(payload.get("bank"), str) else None
    await fulfill_payment_intent(db, intent, bank=bank)
