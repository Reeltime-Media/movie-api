import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.core.guest import get_guest_id, get_or_create_guest_id
from app.core.url_validation import validate_checkout_url, validate_custom_success_url
from app.config import get_settings
from app.dependencies import CurrentUser, DBSession, OptionalUser
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.series import Series
from app.schemas.payment import BakongPaymentIntentRead, PaymentIntentCreate, PaymentIntentRead
from app.services import bakong
from app.services.bakong_settle import qr_is_stale, settle_bakong_intent_if_paid
from app.services.payment import checkout_url, create_intent
from app.services.subscription_plans import resolve_active_plan

router = APIRouter(prefix="/payments", tags=["payments"])

_MIN_USD = Decimal("0.03")


def _read_intent(intent: PaymentIntent) -> PaymentIntentRead:
    # Bakong intents poll in place — there's no redirect target to validate.
    url = (
        validate_checkout_url(checkout_url(intent.intent_id))
        if intent.method == "baray"
        else None
    )
    return PaymentIntentRead(
        intent_id=intent.intent_id,
        order_id=intent.order_id,
        user_id=intent.user_id,
        method=intent.method,
        kind=intent.kind,
        content_id=intent.content_id,
        amount_usd=intent.amount_usd,
        status=intent.status,
        checkout_url=url,
        created_at=intent.created_at,
        resolved_at=intent.resolved_at,
    )


def _bakong_merchant_name(intent: PaymentIntent) -> str:
    return (
        (intent.bakong_merchant_name or "").strip()
        or get_settings().bakong_merchant_name.strip()
        or "Reeltime Media"
    )


def _read_bakong_intent(intent: PaymentIntent) -> BakongPaymentIntentRead:
    return BakongPaymentIntentRead(
        intent_id=intent.intent_id,
        order_id=intent.order_id,
        qr_string=intent.bakong_qr or "",
        amount_usd=intent.amount_usd,
        status=intent.status,
        created_at=intent.created_at,
        merchant_name=_bakong_merchant_name(intent),
    )


def _validate_amount(amount: Decimal | None) -> Decimal:
    if amount is None or amount < _MIN_USD:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="USD payments must be at least 0.03",
        )
    return amount


async def _regenerate_bakong_qr(intent: PaymentIntent) -> None:
    """Issue a fresh KHQR on the same intent; keep previous md5 for late settles."""
    bill_number = uuid.uuid4().hex[:20]
    qr_string, md5, merchant_name = await bakong.generate_khqr(
        intent.amount_usd, bill_number
    )
    intent.bakong_prev_md5 = intent.bakong_md5
    intent.bakong_md5 = md5
    intent.bakong_qr = qr_string
    intent.bakong_merchant_name = merchant_name or intent.bakong_merchant_name
    intent.bakong_qr_created_at = datetime.now(timezone.utc)


@router.post("/movies/{content_id}/intent", response_model=PaymentIntentRead, status_code=201)
async def create_movie_payment_intent(
    content_id: uuid.UUID,
    data: PaymentIntentCreate,
    db: DBSession,
    request: Request,
    response: Response,
    user: OptionalUser,
):
    # BARAY DISABLED — movie checkout uses Bakong (/bakong-intent). Keep body for later.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Baray checkout is disabled",
    )
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
        method="baray",
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
    "/movies/{content_id}/bakong-intent",
    response_model=BakongPaymentIntentRead,
    status_code=201,
)
async def create_movie_bakong_intent(
    content_id: uuid.UUID,
    db: DBSession,
    request: Request,
    response: Response,
    user: OptionalUser,
):
    """Inline KHQR checkout — no redirect. The client polls GET
    /payments/intents/{id}, which actively checks Bakong (no webhook exists).
    A background sweeper also settles paid intents if the tab is closed."""
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
        select(PaymentIntent)
        .where(
            identity_filter,
            PaymentIntent.method == "bakong",
            PaymentIntent.kind == "single",
            PaymentIntent.content_id == content_id,
            PaymentIntent.status == "pending",
        )
        .order_by(PaymentIntent.created_at.asc())
        .with_for_update()
    )
    pending_intent = pending.scalars().first()
    if pending_intent:
        if await settle_bakong_intent_if_paid(db, pending_intent):
            await db.commit()
            await db.refresh(pending_intent)
            return _read_bakong_intent(pending_intent)

        if qr_is_stale(pending_intent):
            await _regenerate_bakong_qr(pending_intent)
            await db.commit()
            await db.refresh(pending_intent)

        return _read_bakong_intent(pending_intent)

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
    bill_number = uuid.uuid4().hex[:20]
    qr_string, md5, merchant_name = await bakong.generate_khqr(amount, bill_number)
    now = datetime.now(timezone.utc)

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
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return _read_bakong_intent(intent)


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
    # BARAY DISABLED — subscription checkout via Baray is paused. Keep body for later.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Baray subscription checkout is disabled",
    )
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
    Poll payment status. Baray fulfillment is webhook-only — this endpoint
    never marks a Baray intent succeeded without gateway confirmation. Bakong
    has no webhook, so for a pending Bakong intent we actively check Bakong
    ourselves right here before responding (sweeper does the same in background).
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

    if intent.method == "bakong" and intent.status == "pending" and intent.bakong_md5:
        if await settle_bakong_intent_if_paid(db, intent):
            await db.commit()
            await db.refresh(intent)
        elif intent.content_id is not None:
            # Recover from duplicate pending intents (race on create): if the
            # user paid a sibling QR for the same title, fulfill that sibling
            # and mark this poll target succeeded without a second purchase.
            identity = (
                (PaymentIntent.user_id == intent.user_id)
                if intent.user_id is not None
                else (PaymentIntent.guest_id == intent.guest_id)
            )
            siblings = await db.execute(
                select(PaymentIntent).where(
                    identity,
                    PaymentIntent.method == "bakong",
                    PaymentIntent.kind == "single",
                    PaymentIntent.content_id == intent.content_id,
                    PaymentIntent.status == "pending",
                    PaymentIntent.intent_id != intent.intent_id,
                    PaymentIntent.bakong_md5.is_not(None),
                )
            )
            for sibling in siblings.scalars().all():
                if await settle_bakong_intent_if_paid(db, sibling):
                    intent.status = "succeeded"
                    intent.resolved_at = sibling.resolved_at
                    await db.commit()
                    await db.refresh(intent)
                    break

    return _read_intent(intent)
