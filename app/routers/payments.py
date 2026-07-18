import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.core.guest import get_guest_id, get_or_create_guest_id
from app.core.url_validation import validate_checkout_url, validate_custom_success_url
from app.dependencies import CurrentUser, DBSession, OptionalUser
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.series import Series
from app.schemas.payment import PaymentIntentCreate, PaymentIntentRead
from app.services.payment import checkout_url, create_intent
from app.services.subscription_plans import resolve_active_plan

router = APIRouter(prefix="/payments", tags=["payments"])

_MIN_USD = Decimal("0.03")


def _read_intent(intent: PaymentIntent) -> PaymentIntentRead:
    url = validate_checkout_url(checkout_url(intent.intent_id))
    return PaymentIntentRead(
        intent_id=intent.intent_id,
        order_id=intent.order_id,
        user_id=intent.user_id,
        kind=intent.kind,
        content_id=intent.content_id,
        amount_usd=intent.amount_usd,
        status=intent.status,
        checkout_url=url,
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
    request: Request,
    response: Response,
    user: OptionalUser,
):
    guest_id = None if user else get_or_create_guest_id(request, response)
    identity_filter = (
        (PaymentIntent.user_id == user.id) if user else (PaymentIntent.guest_id == guest_id)
    )
    purchase_filter = (
        (Purchase.user_id == user.id) if user else (Purchase.guest_id == guest_id)
    )

    existing_purchase = await db.execute(
        select(Purchase).where(purchase_filter, Purchase.content_id == content_id)
    )
    if existing_purchase.scalar_one_or_none():
        raise ConflictError("Movie already purchased")

    pending = await db.execute(
        select(PaymentIntent).where(
            identity_filter,
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
            "user_id": str(user.id) if user else None,
            "guest_id": guest_id,
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
        custom_success_url=(
            validate_custom_success_url(str(data.custom_success_url))
            if data.custom_success_url
            else None
        ),
    )

    intent = PaymentIntent(
        intent_id=baray_intent["_id"],
        order_id=order_id,
        user_id=user.id if user else None,
        guest_id=guest_id,
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
        custom_success_url=(
            validate_custom_success_url(str(data.custom_success_url))
            if data.custom_success_url
            else None
        ),
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


@router.get("/intents/{intent_id}", response_model=PaymentIntentRead)
async def get_payment_intent(
    intent_id: str,
    db: DBSession,
    request: Request,
    user: OptionalUser,
):
    """
    Poll payment status after Baray redirect. Fulfillment is webhook-only;
    this endpoint never marks an intent as succeeded without gateway confirmation.
    """
    if user:
        identity_filter = PaymentIntent.user_id == user.id
    else:
        guest_id = get_guest_id(request)
        if not guest_id:
            raise NotFoundError("Payment intent not found")
        identity_filter = PaymentIntent.guest_id == guest_id
    result = await db.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == intent_id, identity_filter)
    )
    intent = result.scalar_one_or_none()
    if not intent:
        raise NotFoundError("Payment intent not found")
    return _read_intent(intent)
