import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.dependencies import DBSession
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.webhook_event import WebhookEvent
from app.services.payment import verify_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/baray")
async def baray_webhook(request: Request, db: DBSession):
    body = await request.body()
    signature = request.headers.get("X-Baray-Signature", "")

    if not verify_signature(body, signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature"
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON"
        )

    # Persist raw payload before any processing — allows replay on crash
    event = WebhookEvent(
        provider="baray",
        payload=payload,
        received_at=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()  # get id without committing

    try:
        await _process_baray_event(db, payload)
        event.processed_at = datetime.now(timezone.utc)
    except Exception as exc:
        event.error = str(exc)

    await db.commit()
    return {"status": "ok"}


async def _process_baray_event(db, payload: dict) -> None:
    event_type = payload.get("type")
    intent_id = payload.get("intent_id")
    if not intent_id:
        return

    result = await db.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
    )
    intent = result.scalar_one_or_none()
    if not intent:
        return

    now = datetime.now(timezone.utc)

    if event_type == "payment.succeeded":
        intent.status = "succeeded"
        intent.resolved_at = now
        if intent.kind == "single" and intent.content_id:
            purchase = Purchase(
                user_id=intent.user_id,
                content_id=intent.content_id,
                intent_id=intent.intent_id,
                order_id=intent.order_id,
                amount_usd=intent.amount_usd,
            )
            db.add(purchase)

    elif event_type == "payment.failed":
        intent.status = "failed"
        intent.resolved_at = now
