import asyncio
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, DBSession
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services.pagination import paginate_query
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.series import Series
from app.models.transcode_job import TranscodeJob
from app.services.content_delete import delete_transcode_jobs_for_content
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.models.user import User
from app.models.watch_progress import WatchProgress
from app.schemas.content import ContentRead, ContentUpdate, SeasonRead
from app.schemas.series import SeriesRead
from app.schemas.subscription_plan import (
    SubscriptionPlanCreate,
    SubscriptionPlanRead,
    SubscriptionPlanUpdate,
)
from app.services.subscription_plans import list_subscription_plans
from app.services import storage

router = APIRouter(prefix="/admin", tags=["admin"])
_VALID_STATUSES = {"draft", "review", "scheduled", "published"}


class TranscodeJobRead(BaseModel):
    id: uuid.UUID
    content_id: uuid.UUID
    source_key: str
    status: str
    attempts: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MovieAssetUploadStart(BaseModel):
    video_content_type: str | None = None
    poster_content_type: str | None = None


class MovieAssetUploadStartRead(BaseModel):
    source_key: str | None = None
    video_upload_url: str | None = None
    poster_key: str | None = None
    poster_upload_url: str | None = None


class MovieAssetUploadComplete(BaseModel):
    source_key: str | None = None
    poster_key: str | None = None


class DashboardUserSummary(BaseModel):
    total: int
    admins: int
    active: int


class DashboardContentSummary(BaseModel):
    movies: int
    series: int
    published: int
    drafts: int
    review: int
    scheduled: int


class DashboardPaymentSummary(BaseModel):
    total: int
    succeeded: int
    pending: int
    failed: int
    revenue_usd: Decimal


class DashboardTranscodeSummary(BaseModel):
    pending: int
    processing: int
    failed: int


class DashboardSummaryRead(BaseModel):
    users: DashboardUserSummary
    content: DashboardContentSummary
    payments: DashboardPaymentSummary
    transcodes: DashboardTranscodeSummary


class TopTitleReportRead(BaseModel):
    id: uuid.UUID
    title: str
    type: str
    status: str
    revenue_usd: Decimal
    purchase_count: int
    watch_count: int
    completion_count: int


def _poster_extension(content_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(content_type, "jpg")


@router.get("/dashboard-summary", response_model=DashboardSummaryRead)
async def get_dashboard_summary(db: DBSession, _: AdminUser):
    user_counts = await db.execute(
        select(
            func.count(User.id).label("total"),
            func.count(User.id).filter(User.role == "admin").label("admins"),
            func.count(User.id).filter(User.is_active.is_(True)).label("active"),
        )
    )
    users = user_counts.one()

    content_counts = await db.execute(
        select(
            func.count(Content.id).filter(Content.type == "single").label("movies"),
            func.count(Content.id).filter(Content.status == "published").label("published"),
            func.count(Content.id).filter(Content.status == "draft").label("drafts"),
            func.count(Content.id).filter(Content.status == "review").label("review"),
            func.count(Content.id).filter(Content.status == "scheduled").label("scheduled"),
            func.count(Content.id).filter(Content.transcode_status == "pending").label("pending"),
            func.count(Content.id).filter(Content.transcode_status == "processing").label("processing"),
            func.count(Content.id).filter(Content.transcode_status == "failed").label("failed"),
        )
    )
    content = content_counts.one()

    series_count = await db.scalar(select(func.count(Series.id)))

    payment_counts = await db.execute(
        select(
            func.count(PaymentIntent.intent_id).label("total"),
            func.count(PaymentIntent.intent_id).filter(PaymentIntent.status == "succeeded").label("succeeded"),
            func.count(PaymentIntent.intent_id).filter(PaymentIntent.status == "pending").label("pending"),
            func.count(PaymentIntent.intent_id).filter(PaymentIntent.status == "failed").label("failed"),
            func.coalesce(
                func.sum(PaymentIntent.amount_usd).filter(PaymentIntent.status == "succeeded"),
                Decimal("0"),
            ).label("revenue_usd"),
        )
    )
    payments = payment_counts.one()

    return DashboardSummaryRead(
        users=DashboardUserSummary(
            total=users.total,
            admins=users.admins,
            active=users.active,
        ),
        content=DashboardContentSummary(
            movies=content.movies,
            series=series_count or 0,
            published=content.published,
            drafts=content.drafts,
            review=content.review,
            scheduled=content.scheduled,
        ),
        payments=DashboardPaymentSummary(
            total=payments.total,
            succeeded=payments.succeeded,
            pending=payments.pending,
            failed=payments.failed,
            revenue_usd=payments.revenue_usd,
        ),
        transcodes=DashboardTranscodeSummary(
            pending=content.pending,
            processing=content.processing,
            failed=content.failed,
        ),
    )


@router.get("/reports/top-titles", response_model=PaginatedResponse[TopTitleReportRead])
async def list_top_titles(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
):
    purchase_stats = (
        select(
            Purchase.content_id.label("content_id"),
            func.count(Purchase.id).label("purchase_count"),
            func.coalesce(func.sum(Purchase.amount_usd), Decimal("0")).label("revenue_usd"),
        )
        .group_by(Purchase.content_id)
        .subquery()
    )
    watch_stats = (
        select(
            WatchProgress.content_id.label("content_id"),
            func.count(WatchProgress.user_id).label("watch_count"),
            func.count(WatchProgress.user_id)
            .filter(WatchProgress.completed.is_(True))
            .label("completion_count"),
        )
        .group_by(WatchProgress.content_id)
        .subquery()
    )

    stmt = (
        select(
            Content.id,
            Content.title,
            Content.type,
            Content.status,
            func.coalesce(purchase_stats.c.revenue_usd, Decimal("0")).label("revenue_usd"),
            func.coalesce(purchase_stats.c.purchase_count, 0).label("purchase_count"),
            func.coalesce(watch_stats.c.watch_count, 0).label("watch_count"),
            func.coalesce(watch_stats.c.completion_count, 0).label("completion_count"),
        )
        .outerjoin(purchase_stats, purchase_stats.c.content_id == Content.id)
        .outerjoin(watch_stats, watch_stats.c.content_id == Content.id)
        .order_by(
            func.coalesce(purchase_stats.c.revenue_usd, Decimal("0")).desc(),
            func.coalesce(purchase_stats.c.purchase_count, 0).desc(),
            func.coalesce(watch_stats.c.watch_count, 0).desc(),
            Content.created_at.desc(),
        )
    )

    rows, total = await paginate_query(
        db,
        stmt,
        page=pagination.page,
        page_size=pagination.page_size,
        scalar=False,
    )

    return build_paginated_response(
        [
            TopTitleReportRead(
                id=row.id,
                title=row.title,
                type=row.type,
                status=row.status,
                revenue_usd=row.revenue_usd,
                purchase_count=row.purchase_count,
                watch_count=row.watch_count,
                completion_count=row.completion_count,
            )
            for row in rows
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/movies", response_model=PaginatedResponse[ContentRead])
async def list_admin_movies(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
):
    stmt = (
        select(Content)
        .where(Content.type == "single")
        .order_by(Content.created_at.desc())
    )
    items, total = await paginate_query(
        db, stmt, page=pagination.page, page_size=pagination.page_size
    )
    return build_paginated_response(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.patch("/movies/{movie_id}", response_model=ContentRead)
async def update_admin_movie(
    movie_id: uuid.UUID,
    data: ContentUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(Content).where(Content.id == movie_id, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")

    updates = data.model_dump(exclude_unset=True)
    if "status" in updates:
        if updates["status"] not in _VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUSES)}")
        updates["is_published"] = updates["status"] == "published"

    for field, value in updates.items():
        setattr(movie, field, value)

    await db.commit()
    await db.refresh(movie)
    return movie


@router.post("/movies/{movie_id}/assets/start", response_model=MovieAssetUploadStartRead)
async def start_admin_movie_asset_upload(
    movie_id: uuid.UUID,
    data: MovieAssetUploadStart,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(Content).where(Content.id == movie_id, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")

    token = uuid.uuid4().hex[:8]
    source_key: str | None = None
    video_upload_url: str | None = None
    poster_key: str | None = None
    poster_upload_url: str | None = None

    if data.video_content_type:
        source_key = f"raw/{movie_id}-{token}.mp4"
        video_upload_url = storage.generate_presigned_upload_url(
            source_key,
            data.video_content_type,
        )

    if data.poster_content_type:
        poster_key = f"posters/{movie_id}-{token}.{_poster_extension(data.poster_content_type)}"
        poster_upload_url = storage.generate_presigned_upload_url(
            poster_key,
            data.poster_content_type,
        )

    if not source_key and not poster_key:
        raise HTTPException(status_code=422, detail="Choose a video or poster file to replace")

    return MovieAssetUploadStartRead(
        source_key=source_key,
        video_upload_url=video_upload_url,
        poster_key=poster_key,
        poster_upload_url=poster_upload_url,
    )


@router.post("/movies/{movie_id}/assets/complete", response_model=ContentRead)
async def complete_admin_movie_asset_upload(
    movie_id: uuid.UUID,
    data: MovieAssetUploadComplete,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(Content).where(Content.id == movie_id, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")

    if data.source_key:
        if not data.source_key.startswith(f"raw/{movie_id}-"):
            raise HTTPException(status_code=422, detail="source_key does not match movie")
        source_exists = await asyncio.get_event_loop().run_in_executor(
            None,
            storage.object_exists,
            data.source_key,
        )
        if not source_exists:
            raise HTTPException(status_code=409, detail="Video upload is not available in storage yet")

        movie.transcode_status = "pending"
        movie.hls_master_key = None
        movie.duration_seconds = None
        db.add(TranscodeJob(content_id=movie.id, source_key=data.source_key))

    if data.poster_key:
        if not data.poster_key.startswith(f"posters/{movie_id}-"):
            raise HTTPException(status_code=422, detail="poster_key does not match movie")
        poster_exists = await asyncio.get_event_loop().run_in_executor(
            None,
            storage.object_exists,
            data.poster_key,
        )
        if not poster_exists:
            raise HTTPException(status_code=409, detail="Poster upload is not available in storage yet")

        movie.poster_key = data.poster_key

    if not data.source_key and not data.poster_key:
        raise HTTPException(status_code=422, detail="No uploaded assets provided")

    await db.commit()
    await db.refresh(movie)
    return movie


@router.delete("/movies/{movie_id}", status_code=204)
async def delete_admin_movie(movie_id: uuid.UUID, db: DBSession, _: AdminUser):
    result = await db.execute(
        select(Content).where(Content.id == movie_id, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")
    await delete_transcode_jobs_for_content(db, movie_id)
    await db.delete(movie)
    await db.commit()


@router.get("/transcode-jobs", response_model=PaginatedResponse[TranscodeJobRead])
async def list_transcode_jobs(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
    status: str | None = Query(
        default=None,
        description="Filter by job status: queued, running, success, failed",
    ),
):
    stmt = select(TranscodeJob).order_by(TranscodeJob.created_at.desc())
    if status:
        stmt = stmt.where(TranscodeJob.status == status)
    items, total = await paginate_query(
        db, stmt, page=pagination.page, page_size=pagination.page_size
    )
    return build_paginated_response(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("/transcode-jobs/{job_id}/retry", response_model=TranscodeJobRead)
async def retry_transcode_job(job_id: uuid.UUID, db: DBSession, _: AdminUser):
    result = await db.execute(select(TranscodeJob).where(TranscodeJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Transcode job not found")
    job.status = "queued"
    job.error = None
    await db.commit()
    await db.refresh(job)
    return job


class AdminPaymentRead(BaseModel):
    intent_id: str
    order_id: str
    user_id: uuid.UUID
    user_email: str
    user_full_name: str | None
    kind: str
    content_id: uuid.UUID | None
    amount_usd: Decimal
    status: str
    created_at: datetime
    resolved_at: datetime | None


@router.get("/payments", response_model=PaginatedResponse[AdminPaymentRead])
async def list_admin_payments(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
):
    stmt = (
        select(
            PaymentIntent,
            User.email,
            User.full_name,
        )
        .join(User, User.id == PaymentIntent.user_id)
        .order_by(PaymentIntent.created_at.desc())
    )
    rows, total = await paginate_query(
        db,
        stmt,
        page=pagination.page,
        page_size=pagination.page_size,
        scalar=False,
    )
    return build_paginated_response(
        [
            AdminPaymentRead(
                intent_id=intent.intent_id,
                order_id=intent.order_id,
                user_id=intent.user_id,
                user_email=email,
                user_full_name=full_name,
                kind=intent.kind,
                content_id=intent.content_id,
                amount_usd=intent.amount_usd,
                status=intent.status,
                created_at=intent.created_at,
                resolved_at=intent.resolved_at,
            )
            for intent, email, full_name in rows
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/subscription-plans", response_model=list[SubscriptionPlanRead])
async def list_admin_subscription_plans(db: DBSession, _: AdminUser):
    try:
        return await list_subscription_plans(db)
    except Exception as exc:
        message = str(exc).lower()
        if "subscription_plans" in message or "does not exist" in message or "undefinedtable" in message:
            raise HTTPException(
                status_code=503,
                detail=(
                    "subscription_plans table is missing. "
                    "Run: cd movie-api && alembic upgrade head"
                ),
            ) from exc
        raise HTTPException(status_code=500, detail="Could not load subscription plans") from exc


@router.post("/subscription-plans", response_model=SubscriptionPlanRead, status_code=201)
async def create_admin_subscription_plan(
    data: SubscriptionPlanCreate,
    db: DBSession,
    _: AdminUser,
):
    existing = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.code == data.code)
    )
    if existing.scalar_one_or_none():
        raise ConflictError("A plan with this code already exists")

    plan = SubscriptionPlan(**data.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.patch("/subscription-plans/{plan_id}", response_model=SubscriptionPlanRead)
async def update_admin_subscription_plan(
    plan_id: uuid.UUID,
    data: SubscriptionPlanUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Subscription plan not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)

    await db.commit()
    await db.refresh(plan)
    return plan


@router.delete("/subscription-plans/{plan_id}", status_code=204)
async def delete_admin_subscription_plan(
    plan_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Subscription plan not found")

    in_use = await db.scalar(
        select(func.count(Subscription.id)).where(Subscription.plan == plan.code)
    )
    if in_use:
        raise ConflictError(
            "This plan has active subscriptions and cannot be deleted. Deactivate it instead."
        )

    await db.delete(plan)
    await db.commit()


@router.get("/series", response_model=PaginatedResponse[SeriesRead])
async def list_admin_series(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
):
    stmt = select(Series).order_by(Series.created_at.desc())
    items, total = await paginate_query(
        db, stmt, page=pagination.page, page_size=pagination.page_size
    )
    return build_paginated_response(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/series/{series_slug}/episodes", response_model=list[SeasonRead])
async def list_admin_series_episodes(series_slug: str, db: DBSession, _: AdminUser):
    """All episodes for a series (draft + published), grouped by season."""
    series_result = await db.execute(select(Series).where(Series.slug == series_slug))
    series = series_result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")

    eps_result = await db.execute(
        select(Content)
        .where(Content.series_id == series.id)
        .order_by(Content.season_number, Content.episode_number)
    )
    episodes = eps_result.scalars().all()

    seasons: dict[int, list[Content]] = {}
    for ep in episodes:
        sn = ep.season_number or 1
        seasons.setdefault(sn, []).append(ep)

    return [
        SeasonRead(season_number=sn, episodes=eps)
        for sn, eps in sorted(seasons.items())
    ]
