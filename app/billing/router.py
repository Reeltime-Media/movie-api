"""HTTP routes for `/payments/*` — thin handlers over billing domain services.

`router` is always mounted. `baray_router` and `bakong_watcher_router`
are mounted only when enabled via settings.
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app.billing.constants import SERIES_UNLOCK_PRICE_USD
from app.billing.intent_helpers import (
    read_bakong_intent as _read_bakong_intent,
)
from app.billing.intent_helpers import (
    read_payment_intent as _read_intent,
)
from app.billing.intents import (
    create_or_reuse_movie_bakong_intent,
    create_or_reuse_series_bakong_intent,
    create_or_reuse_subscription_bakong_intent,
    load_buyer_intent,
    settle_pending_intent_on_poll,
)
from app.billing.schemas import (
    BakongPaymentIntentRead,
    BakongPendingListRead,
    BakongWebhookPayload,
    CatalogPricingRead,
    PaymentIntentCreate,
    PaymentIntentRead,
)
from app.config import get_settings
from app.core.guest import get_guest_id, get_or_create_guest_id
from app.core.money import MIN_PAID_USD
from app.dependencies import CurrentUser, DBSession, OptionalUser
from app.rate_limit import limiter
from app.services.series import get_series_or_404

router = APIRouter(prefix="/payments", tags=["payments"])
baray_router = APIRouter(prefix="/payments", tags=["payments"])
bakong_watcher_router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/pricing", response_model=CatalogPricingRead)
def get_catalog_pricing():
    """Flat catalog amounts used by checkout — client display should match these."""
    return CatalogPricingRead(
        series_unlock_usd=SERIES_UNLOCK_PRICE_USD,
        min_paid_usd=MIN_PAID_USD,
    )


@baray_router.post("/movies/{content_id}/intent", response_model=PaymentIntentRead, status_code=201)
async def create_movie_payment_intent(
    content_id: uuid.UUID,
    data: PaymentIntentCreate,
    db: DBSession,
    request: Request,
    response: Response,
    user: OptionalUser,
):
    # BARAY DISABLED — movie checkout uses Bakong (/bakong-intent). Keep body for later.
    _ = (content_id, data, db, request, response, user)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Baray checkout is disabled",
    )


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
    intent = await create_or_reuse_movie_bakong_intent(
        db, content_id=content_id, user=user, guest_id=guest_id
    )
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
    response: Response,
    user: OptionalUser,
):
    """Inline KHQR checkout for a one-time series unlock — same guest/user
    Bakong flow as a single movie. No subscription package required."""
    series = await get_series_or_404(db, slug, published_only=True)
    guest_id = None if user else get_or_create_guest_id(request, response)
    intent = await create_or_reuse_series_bakong_intent(
        db, series=series, user=user, guest_id=guest_id
    )
    return _read_bakong_intent(intent)


@baray_router.post(
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
    _ = (series_id, data, db, current_user)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Baray subscription checkout is disabled",
    )


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
    _ = request  # SlowAPI needs Request on limited routes
    intent = await create_or_reuse_subscription_bakong_intent(
        db, user=current_user, plan_code=plan_code
    )
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

    When bakong_nbc_settle_enabled: open checkout may call NBC
    check_transaction_by_md5 (cached / quota-capped). Unlock fallback is
    admin Mark paid. Bank-credit webhook settle is disabled.
    """
    guest_id = None if user else get_guest_id(request)
    intent = await load_buyer_intent(db, intent_id=intent_id, user=user, guest_id=guest_id)
    intent = await settle_pending_intent_on_poll(db, intent)
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


@bakong_watcher_router.get("/bakong/pending", response_model=BakongPendingListRead)
@limiter.limit("60/minute")
async def list_pending_bakong_payments(
    request: Request,
    db: DBSession,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    """DISABLED — Cambodia watcher / bank-credit feed not in use."""
    _ = (request, db, x_api_key)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Bakong pending feed disabled (no bank-credit / watcher settle)",
    )


@bakong_watcher_router.post("/bakong/webhook")
@limiter.limit("120/minute")
async def bakong_payment_webhook(
    request: Request,
    db: DBSession,
    payload: BakongWebhookPayload,
    x_bakong_webhook_secret: str | None = Header(default=None),
):
    """DISABLED — bank-credit / external watcher settle not available."""
    _ = (request, db, payload, x_bakong_webhook_secret)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Bakong webhook settle disabled (no bank-credit integration)",
    )
