import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from app.rate_limit import limiter
from sqlalchemy import select

from app.core.webhook_auth import verify_baray_webhook
from app.dependencies import DBSession
from app.models.payment_intent import PaymentIntent
from app.models.webhook_event import WebhookEvent
from app.services.payment import decrypt_order_id
from app.services.payment_fulfillment import fulfill_payment_intent

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# BARAY DISABLED — router is not mounted in main.py. Handler kept for later.


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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON"
        )
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
        received_at=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()

    try:
        await _process_baray_event(db, order_id, payload)
        event.processed_at = datetime.now(timezone.utc)
    except Exception as exc:
        event.error = str(exc)

    await db.commit()
    return {"status": "ok"}


async def _process_baray_event(db, order_id: str, payload: dict) -> None:
    result = await db.execute(
        select(PaymentIntent).where(PaymentIntent.order_id == order_id)
    )
    intent = result.scalar_one_or_none()
    if not intent:
        return

    bank = payload.get("bank") if isinstance(payload.get("bank"), str) else None
    await fulfill_payment_intent(db, intent, bank=bank)
