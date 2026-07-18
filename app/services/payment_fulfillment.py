"""Fulfill payment intents after verified Baray webhook (or idempotent retry)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.subscription import Subscription
from app.models.subscription_payment import SubscriptionPayment
from app.services.subscription_plans import get_subscription_plan_by_code, resolve_active_plan


async def fulfill_payment_intent(
    db: AsyncSession,
    intent: PaymentIntent,
    *,
    bank: str | None = None,
) -> None:
    """Mark intent succeeded and create purchase/subscription side effects. Idempotent."""
    if intent.status == "succeeded":
        return

    now = datetime.now(timezone.utc)
    intent.status = "succeeded"
    intent.resolved_at = now

    if intent.kind == "single" and intent.content_id:
        existing = await db.execute(
            select(Purchase).where(Purchase.intent_id == intent.intent_id)
        )
        if existing.scalar_one_or_none():
            return
        db.add(
            Purchase(
                user_id=intent.user_id,
                guest_id=intent.guest_id,
                content_id=intent.content_id,
                intent_id=intent.intent_id,
                order_id=intent.order_id,
                bank=bank,
                amount_usd=intent.amount_usd,
            )
        )
        return

    if intent.kind != "sub":
        return

    existing_payment = await db.execute(
        select(SubscriptionPayment).where(
            SubscriptionPayment.intent_id == intent.intent_id
        )
    )
    if existing_payment.scalar_one_or_none():
        return

    default_plan = await resolve_active_plan(db)
    sub_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == intent.user_id)
        .order_by(Subscription.current_period_end.desc())
    )
    subscription = sub_result.scalars().first()
    plan = default_plan
    if subscription:
        existing_plan = await get_subscription_plan_by_code(db, subscription.plan)
        if existing_plan:
            plan = existing_plan

    if subscription and subscription.current_period_end > now:
        period_start = subscription.current_period_end
    else:
        period_start = now

    period_end = period_start + timedelta(days=plan.billing_interval_days)

    if not subscription:
        subscription = Subscription(
            user_id=intent.user_id,
            plan=plan.code,
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
