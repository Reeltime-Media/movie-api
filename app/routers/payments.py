import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import CurrentUser, DBSession
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.series import Series
from app.models.subscription import Subscription
from app.models.subscription_payment import SubscriptionPayment
from app.schemas.payment import PaymentIntentCreate, PaymentIntentRead
from app.services.payment import checkout_url, create_intent
from app.services.subscription_plans import get_subscription_plan_by_code, resolve_active_plan

router = APIRouter(prefix="/payments", tags=["payments"])

_MIN_USD = Decimal("0.03")


def _read_intent(intent: PaymentIntent) -> PaymentIntentRead:
    return PaymentIntentRead(
        intent_id=intent.intent_id,
        order_id=intent.order_id,
        user_id=intent.user_id,
        kind=intent.kind,
        content_id=intent.content_id,
        amount_usd=intent.amount_usd,
        status=intent.status,
        checkout_url=checkout_url(intent.intent_id),
        created_at=intent.created_at,
        resolved_at=intent.resolved_at,
    )


def _validate_amount(amount: Decimal | None) -> Decimal:
    if amount is None or amount < _MIN_USD:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="USD payments must be at least 0.03",
        )
    return amount


@router.post("/movies/{content_id}/intent", response_model=PaymentIntentRead, status_code=201)
async def create_movie_payment_intent(
    content_id: uuid.UUID,
    data: PaymentIntentCreate,
    db: DBSession,
    current_user: CurrentUser,
):
    existing_purchase = await db.execute(
        select(Purchase).where(
            Purchase.user_id == current_user.id,
            Purchase.content_id == content_id,
        )
    )
    if existing_purchase.scalar_one_or_none():
        raise ConflictError("Movie already purchased")

    pending = await db.execute(
        select(PaymentIntent).where(
            PaymentIntent.user_id == current_user.id,
            PaymentIntent.kind == "single",
            PaymentIntent.content_id == content_id,
            PaymentIntent.status == "pending",
        )
    )
    pending_intent = pending.scalar_one_or_none()
    if pending_intent:
        return _read_intent(pending_intent)

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

    amount = _validate_amount(movie.price_usd)
    order_id = f"movie-{uuid.uuid4().hex}"
    baray_intent = await create_intent(
        amount_usd=amount,
        order_id=order_id,
        tracking={
            "kind": "single",
            "user_id": str(current_user.id),
            "content_id": str(movie.id),
        },
        order_details={
            "items": [
                {
                    "name": movie.title,
                    "price": float(amount),
                }
            ]
        },
        custom_success_url=str(data.custom_success_url) if data.custom_success_url else None,
    )

    intent = PaymentIntent(
        intent_id=baray_intent["_id"],
        order_id=order_id,
        user_id=current_user.id,
        kind="single",
        content_id=movie.id,
        amount_usd=amount,
        status="pending",
    )
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return _read_intent(intent)


@router.post(
    "/series/{series_id}/subscription-intent",
    response_model=PaymentIntentRead,
    status_code=201,
)
async def create_series_subscription_payment_intent(
    series_id: uuid.UUID,
    data: PaymentIntentCreate,
    db: DBSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(Series).where(
            Series.id == series_id,
            Series.is_published.is_(True),
        )
    )
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")

    plan = await resolve_active_plan(db)
    amount = _validate_amount(plan.price_usd)
    order_id = f"sub-{uuid.uuid4().hex}"
    baray_intent = await create_intent(
        amount_usd=amount,
        order_id=order_id,
        tracking={
            "kind": "sub",
            "plan": plan.code,
            "user_id": str(current_user.id),
            "series_id": str(series.id),
        },
        order_details={
            "items": [
                {
                    "name": f"{plan.name} — {series.title}",
                    "price": float(amount),
                }
            ]
        },
        custom_success_url=str(data.custom_success_url) if data.custom_success_url else None,
    )

    intent = PaymentIntent(
        intent_id=baray_intent["_id"],
        order_id=order_id,
        user_id=current_user.id,
        kind="sub",
        content_id=None,
        amount_usd=amount,
        status="pending",
    )
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return _read_intent(intent)


@router.post("/intents/{intent_id}/complete", response_model=PaymentIntentRead)
async def complete_payment_intent(
    intent_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    """
    Called by the client success page after Baray redirects back.
    Fallback for when the Baray webhook is delayed or not yet configured.
    Idempotent — safe to call even if the webhook already processed the intent.
    """
    result = await db.execute(
        select(PaymentIntent).where(
            PaymentIntent.intent_id == intent_id,
            PaymentIntent.user_id == current_user.id,
        )
    )
    intent = result.scalar_one_or_none()
    if not intent:
        raise NotFoundError("Payment intent not found")

    if intent.status == "succeeded":
        return _read_intent(intent)

    now = datetime.now(timezone.utc)
    intent.status = "succeeded"
    intent.resolved_at = now

    if intent.kind == "single" and intent.content_id:
        existing = await db.execute(
            select(Purchase).where(Purchase.intent_id == intent.intent_id)
        )
        if not existing.scalar_one_or_none():
            db.add(Purchase(
                user_id=intent.user_id,
                content_id=intent.content_id,
                intent_id=intent.intent_id,
                order_id=intent.order_id,
                amount_usd=intent.amount_usd,
            ))

    elif intent.kind == "sub":
        existing_payment = await db.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.intent_id == intent.intent_id
            )
        )
        if not existing_payment.scalar_one_or_none():
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
            period_start = (
                subscription.current_period_end
                if subscription and subscription.current_period_end > now
                else now
            )
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

            db.add(SubscriptionPayment(
                subscription_id=subscription.id,
                intent_id=intent.intent_id,
                order_id=intent.order_id,
                amount_usd=intent.amount_usd,
                period_extended_to=period_end,
            ))

    await db.commit()
    await db.refresh(intent)
    return _read_intent(intent)
