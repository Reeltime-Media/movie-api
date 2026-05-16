import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.dependencies import DBSession
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.subscription import Subscription
from app.models.subscription_payment import SubscriptionPayment
from app.models.webhook_event import WebhookEvent
from app.services.payment import decrypt_order_id

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/baray")
async def baray_webhook(request: Request, db: DBSession):
    body = await request.body()

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

    # Persist raw payload before any processing so failed events can be inspected.
    event = WebhookEvent(
        provider="baray",
        payload=payload,
        received_at=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()  # get id without committing

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

    now = datetime.now(timezone.utc)
    bank = payload.get("bank") if isinstance(payload.get("bank"), str) else None

    if intent.status == "succeeded":
        return

    intent.status = "succeeded"
    intent.resolved_at = now

    if intent.kind == "single" and intent.content_id:
        existing_purchase = await db.execute(
            select(Purchase).where(Purchase.intent_id == intent.intent_id)
        )
        if existing_purchase.scalar_one_or_none():
            return

        purchase = Purchase(
            user_id=intent.user_id,
            content_id=intent.content_id,
            intent_id=intent.intent_id,
            order_id=intent.order_id,
            bank=bank,
            amount_usd=intent.amount_usd,
        )
        db.add(purchase)
        return

    if intent.kind == "sub":
        existing_payment = await db.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.intent_id == intent.intent_id
            )
        )
        if existing_payment.scalar_one_or_none():
            return

        sub_result = await db.execute(
            select(Subscription)
            .where(
                Subscription.user_id == intent.user_id,
                Subscription.plan == "series_monthly",
            )
            .order_by(Subscription.current_period_end.desc())
        )
        subscription = sub_result.scalars().first()

        if subscription and subscription.current_period_end > now:
            period_start = subscription.current_period_end
        else:
            period_start = now

        period_end = period_start + timedelta(days=30)

        if not subscription:
            subscription = Subscription(
                user_id=intent.user_id,
                plan="series_monthly",
                status="active",
                current_period_start=now,
                current_period_end=period_end,
            )
            db.add(subscription)
            await db.flush()
        else:
            subscription.status = "active"
            if subscription.current_period_end <= now:
                subscription.current_period_start = now
            subscription.current_period_end = period_end

        db.add(
            SubscriptionPayment(
                subscription_id=subscription.id,
                intent_id=intent.intent_id,
                order_id=intent.order_id,
                bank=bank,
                amount_usd=intent.amount_usd,
                period_extended_to=period_end,
            )
        )
