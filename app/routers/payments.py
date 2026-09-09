import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select

from app.core.exceptions import ConflictError, NotFoundError
from app.core.guest import get_guest_id, get_or_create_guest_id
from app.core.url_validation import validate_checkout_url, validate_custom_success_url
from app.config import get_settings
from app.dependencies import CurrentUser, DBSession, OptionalUser
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.series import Series
from app.models.series_purchase import SeriesPurchase
from app.rate_limit import limiter
from app.schemas.payment import (
    BakongPaymentIntentRead,
    BakongPendingIntentRead,
    BakongPendingListRead,
    BakongWebhookPayload,
    PaymentIntentCreate,
    PaymentIntentRead,
)
from app.services import bakong
from app.services.bakong_settle import (
    bakong_qr_confirmed_unpaid,
    qr_is_stale,
    settle_bakong_intent_if_paid,
)
from app.services.content_access import user_has_active_subscription
from app.services.payment import checkout_url, create_intent
from app.services.payment_fulfillment import fulfill_payment_intent
from app.services.series import get_series_or_404
from app.services.subscription_plans import resolve_active_plan

router = APIRouter(prefix="/payments", tags=["payments"])

_MIN_USD = Decimal("0.03")
# Flat one-time price to unlock a single series — matches the "Mini" pricing
# card (lib/pricing-tiers.ts on the client); series have no per-title unlock
# price of their own (Series.monthly_price_usd is for the old subscription-only
# design), so this is a constant rather than something resolved per series.
_SERIES_UNLOCK_PRICE_USD = Decimal("2.50")


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
        series_id=intent.series_id,
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


async def _mark_succeeded_if_already_purchased(
    db: DBSession,
    intent: PaymentIntent,
) -> bool:
    """Unstick QR UI when the movie is already owned but this intent is still pending."""
    if intent.content_id is None:
        return False
    if intent.user_id is not None:
        owner = Purchase.user_id == intent.user_id
    elif intent.guest_id:
        owner = Purchase.guest_id == intent.guest_id
    else:
        return False
    existing = await db.execute(
        select(Purchase.id).where(Purchase.content_id == intent.content_id, owner).limit(1)
    )
    if existing.scalar_one_or_none() is None:
        return False
    intent.status = "succeeded"
    intent.resolved_at = datetime.now(timezone.utc)
    return True


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
@limiter.limit("8/minute")
async def create_movie_bakong_intent(
    content_id: uuid.UUID,
    db: DBSession,
    request: Request,
    response: Response,
    user: OptionalUser,
):
    """Inline KHQR checkout — no redirect. Client polls DB status; settle is
    admin Mark paid / bakong webhook (NBC check disabled by default)."""
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
        # Fresh QR: reuse immediately. Do NOT NBC-check here — open checkout
        # tabs + sweeper already poll; extra checks burn the daily quota.
        if not qr_is_stale(pending_intent):
            if await _mark_succeeded_if_already_purchased(db, pending_intent):
                await db.commit()
                await db.refresh(pending_intent)
            return _read_bakong_intent(pending_intent)

        # Stale QR: settle if paid. Only mint a new QR when NBC confirmed unpaid.
        # If the check is rate-limited / down, keep this QR — regenerating is how
        # customers got charged twice for the same movie.
        if await settle_bakong_intent_if_paid(db, pending_intent):
            await db.commit()
            await db.refresh(pending_intent)
            return _read_bakong_intent(pending_intent)
        if await _mark_succeeded_if_already_purchased(db, pending_intent):
            await db.commit()
            await db.refresh(pending_intent)
            return _read_bakong_intent(pending_intent)

        if await bakong_qr_confirmed_unpaid(pending_intent):
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
    "/series/{slug}/unlock-bakong-intent",
    response_model=BakongPaymentIntentRead,
    status_code=201,
)
@limiter.limit("8/minute")
async def create_series_unlock_bakong_intent(
    slug: str,
    db: DBSession,
    request: Request,
    current_user: CurrentUser,
):
    """Inline KHQR checkout for a one-time "unlock this series" purchase —
    mirrors the movie Bakong flow. The client polls GET /payments/intents/{id}."""
    series = await get_series_or_404(db, slug, published_only=True)

    if await user_has_active_subscription(db, current_user.id):
        raise ConflictError("You already have an active subscription")

    existing_purchase = await db.execute(
        select(SeriesPurchase).where(
            SeriesPurchase.user_id == current_user.id,
            SeriesPurchase.series_id == series.id,
        )
    )
    if existing_purchase.scalar_one_or_none():
        raise ConflictError("Series already unlocked")

    pending = await db.execute(
        select(PaymentIntent)
        .where(
            PaymentIntent.user_id == current_user.id,
            PaymentIntent.method == "bakong",
            PaymentIntent.kind == "series",
            PaymentIntent.series_id == series.id,
            PaymentIntent.status == "pending",
        )
        .order_by(PaymentIntent.created_at.asc())
        .with_for_update()
    )
    pending_intent = pending.scalars().first()
    if pending_intent:
        # Fast path: reuse a fresh QR immediately. Settle checks happen on poll /
        # sweeper — do not block QR display on a Bakong round-trip here.
        if not qr_is_stale(pending_intent):
            return _read_bakong_intent(pending_intent)

        # Stale QR: settle if paid. Only mint a new QR when NBC confirmed unpaid.
        if await settle_bakong_intent_if_paid(db, pending_intent):
            await db.commit()
            await db.refresh(pending_intent)
            return _read_bakong_intent(pending_intent)

        if await bakong_qr_confirmed_unpaid(pending_intent):
            await _regenerate_bakong_qr(pending_intent)
            await db.commit()
            await db.refresh(pending_intent)
        return _read_bakong_intent(pending_intent)

    amount = _validate_amount(_SERIES_UNLOCK_PRICE_USD)
    order_id = f"series-{uuid.uuid4().hex}"
    bill_number = uuid.uuid4().hex[:20]
    qr_string, md5, merchant_name = await bakong.generate_khqr(amount, bill_number)
    now = datetime.now(timezone.utc)

    intent = PaymentIntent(
        intent_id=f"bkg-{uuid.uuid4().hex}",
        order_id=order_id,
        user_id=current_user.id,
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


@router.post(
    "/subscription-bakong-intent",
    response_model=BakongPaymentIntentRead,
    status_code=201,
)
@limiter.limit("8/minute")
async def create_subscription_bakong_intent(
    db: DBSession,
    request: Request,
    current_user: CurrentUser,
    plan_code: str | None = None,
):
    """Inline KHQR checkout for a subscription plan — mirrors the movie
    Bakong flow. The client polls GET /payments/intents/{id}.
    Subscriptions aren't series-scoped (see fulfill_payment_intent), so
    unlike movie checkout this isn't keyed to any particular content."""
    plan = await resolve_active_plan(db, plan_code)
    amount = _validate_amount(plan.price_usd)

    # Pending-intent reuse is scoped to this plan's price — PaymentIntent has
    # no plan_code column, so amount_usd is what stops a switch from Value to
    # Premium (say) from silently reusing a cheaper still-pending QR.
    pending = await db.execute(
        select(PaymentIntent)
        .where(
            PaymentIntent.user_id == current_user.id,
            PaymentIntent.method == "bakong",
            PaymentIntent.kind == "sub",
            PaymentIntent.status == "pending",
            PaymentIntent.amount_usd == amount,
        )
        .order_by(PaymentIntent.created_at.asc())
        .with_for_update()
    )
    pending_intent = pending.scalars().first()
    if pending_intent:
        # Fast path: reuse a fresh QR immediately. Settle checks happen on poll /
        # sweeper — do not block QR display on a Bakong round-trip here.
        if not qr_is_stale(pending_intent):
            return _read_bakong_intent(pending_intent)

        # Stale QR: settle if paid. Only mint a new QR when NBC confirmed unpaid.
        if await settle_bakong_intent_if_paid(db, pending_intent):
            await db.commit()
            await db.refresh(pending_intent)
            return _read_bakong_intent(pending_intent)

        if await bakong_qr_confirmed_unpaid(pending_intent):
            await _regenerate_bakong_qr(pending_intent)
            await db.commit()
            await db.refresh(pending_intent)
        return _read_bakong_intent(pending_intent)

    order_id = f"sub-{plan.code}-{uuid.uuid4().hex}"
    bill_number = uuid.uuid4().hex[:20]
    qr_string, md5, merchant_name = await bakong.generate_khqr(amount, bill_number)
    now = datetime.now(timezone.utc)

    intent = PaymentIntent(
        intent_id=f"bkg-{uuid.uuid4().hex}",
        order_id=order_id,
        user_id=current_user.id,
        method="bakong",
        bakong_md5=md5,
        bakong_qr=qr_string,
        bakong_merchant_name=merchant_name or get_settings().bakong_merchant_name or None,
        bakong_qr_created_at=now,
        kind="sub",
        content_id=None,
        amount_usd=amount,
        status="pending",
    )
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return _read_bakong_intent(intent)


@router.get("/intents/{intent_id}", response_model=PaymentIntentRead)
@limiter.limit("30/minute")
async def get_payment_intent(
    intent_id: str,
    db: DBSession,
    request: Request,
    user: OptionalUser,
):
    """
    Poll payment status. Returns DB state only.

    Bakong self-settle mode does not call NBC here — unlock happens via
    admin Mark paid or POST /payments/bakong/webhook. Optional legacy NBC
    settle remains behind bakong_nbc_settle_enabled.
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

    if intent.method == "bakong" and intent.status == "pending":
        from app.services.bakong_settle import nbc_settle_enabled

        if await _mark_succeeded_if_already_purchased(db, intent):
            await db.commit()
            await db.refresh(intent)
            return _read_intent(intent)

        if nbc_settle_enabled() and intent.bakong_md5:
            from app.services.bakong_check_cache import mark_intent_polled
            from app.services.bakong_quota import bakong_checks_blocked

            if bakong_checks_blocked():
                mark_intent_polled(intent.intent_id)
                return _read_intent(intent)

            if await settle_bakong_intent_if_paid(db, intent):
                await db.commit()
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
                    intent.status = "succeeded"
                    intent.resolved_at = sibling.resolved_at
                    await db.commit()
                    await db.refresh(intent)
            mark_intent_polled(intent.intent_id)

    return _read_intent(intent)


def _bakong_webhook_reports_paid(payload: BakongWebhookPayload) -> bool:
    if payload.paid is True:
        return True
    status_raw = (payload.status or "").strip().lower()
    return status_raw in {"success", "succeeded", "paid", "completed"}


def _require_bakong_service_api_key(x_api_key: str | None) -> None:
    """Auth for Cambodia payment-bakong → movie-api calls (shared service key)."""
    expected = (get_settings().bakong_service_api_key or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BAKONG_SERVICE_API_KEY is not configured",
        )
    provided = (x_api_key or "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )


@router.get("/bakong/pending", response_model=BakongPendingListRead)
@limiter.limit("60/minute")
async def list_pending_bakong_payments(
    request: Request,
    db: DBSession,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    """Recent unpaid Bakong QRs for the Cambodia watcher (no NBC call here)."""
    _ = request
    _require_bakong_service_api_key(x_api_key)
    settings = get_settings()
    window_minutes = min(120, max(5, settings.bakong_pending_window_minutes))
    limit = min(50, max(1, settings.bakong_pending_limit))
    window_start = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    qr_age = func.coalesce(PaymentIntent.bakong_qr_created_at, PaymentIntent.created_at)

    result = await db.execute(
        select(PaymentIntent)
        .where(
            PaymentIntent.method == "bakong",
            PaymentIntent.status == "pending",
            PaymentIntent.bakong_md5.is_not(None),
            qr_age >= window_start,
        )
        .order_by(qr_age.desc())
        .limit(limit)
    )
    intents = result.scalars().all()
    return BakongPendingListRead(
        items=[
            BakongPendingIntentRead(
                intent_id=intent.intent_id,
                md5=intent.bakong_md5 or "",
                prev_md5=intent.bakong_prev_md5,
                created_at=intent.created_at,
                qr_created_at=intent.bakong_qr_created_at,
            )
            for intent in intents
            if intent.bakong_md5
        ]
    )


@router.post("/bakong/webhook")
@limiter.limit("120/minute")
async def bakong_payment_webhook(
    request: Request,
    db: DBSession,
    payload: BakongWebhookPayload,
    x_bakong_webhook_secret: str | None = Header(default=None),
):
    """Settle a Bakong intent from an external watcher (no NBC call).

    Auth: header ``X-Bakong-Webhook-Secret`` must match ``BAKONG_WEBHOOK_SECRET``.
    Compatible with self-hosted KHQR watchers that POST ``{md5, status}``.
    """
    _ = request
    settings = get_settings()
    expected = (settings.bakong_webhook_secret or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bakong webhook is not configured",
        )
    provided = (x_bakong_webhook_secret or "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )

    if not _bakong_webhook_reports_paid(payload):
        return {"status": "ignored", "reason": "not_paid"}

    intent: PaymentIntent | None = None
    if payload.intent_id:
        result = await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == payload.intent_id)
        )
        intent = result.scalar_one_or_none()
    elif payload.md5:
        md5 = payload.md5.strip()
        result = await db.execute(
            select(PaymentIntent)
            .where(
                PaymentIntent.method == "bakong",
                or_(
                    PaymentIntent.bakong_md5 == md5,
                    PaymentIntent.bakong_prev_md5 == md5,
                ),
            )
            .order_by(PaymentIntent.created_at.desc())
            .limit(1)
        )
        intent = result.scalars().first()
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="md5 or intent_id is required",
        )

    if not intent:
        # Acknowledge so watchers do not retry forever for unknown QRs.
        return {"status": "ok", "matched": False}

    if intent.status == "succeeded":
        return {
            "status": "ok",
            "matched": True,
            "intent_id": intent.intent_id,
            "already_succeeded": True,
        }

    await fulfill_payment_intent(db, intent, bank="bakong_webhook")
    await db.commit()
    return {
        "status": "ok",
        "matched": True,
        "intent_id": intent.intent_id,
        "already_succeeded": False,
    }
