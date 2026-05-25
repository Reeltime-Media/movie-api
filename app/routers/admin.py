import asyncio
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from app.core.exceptions import ConflictError, NotFoundError
from app.core.money import validate_usd_price
from app.dependencies import AdminUser, DBSession
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services.pagination import paginate_query
from app.models.comment import Comment
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.series import Series
from app.models.transcode_job import TranscodeJob
from app.services.content_delete import (
    delete_content_dependencies,
    delete_content_dependencies_for_series,
)
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.models.user import User
from app.models.watch_progress import WatchProgress
from app.schemas.comment import CommentRead, CommentUpdate
from app.schemas.content import AdminContentRead, ContentRead, ContentUpdate, SeasonRead
from app.schemas.series import SeriesRead
from app.schemas.subscription_plan import (
    SubscriptionPlanCreate,
    SubscriptionPlanRead,
    SubscriptionPlanUpdate,
)
from app.services.comments import (
    ensure_commentable_movie,
    get_comment_or_404,
    soft_delete_comment,
    to_comment_read,
    update_comment_body,
)
from app.services.subscription_plans import list_subscription_plans
from app.services import storage
from app.services import r2_keys
from app.services.content_publish import ensure_movie_publishable
from app.services.runtime import apply_runtime_minutes
from app.routers.movies import _unique_slug

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
    content_title: str | None = None
    content_type: str | None = None
    content_slug: str | None = None
    series_id: uuid.UUID | None = None
    series_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None

    model_config = {"from_attributes": True}


def _transcode_job_row_to_read(row) -> TranscodeJobRead:
    (
        job,
        content_title,
        content_type,
        content_slug,
        series_id,
        series_title,
        season_number,
        episode_number,
    ) = row
    return TranscodeJobRead(
        id=job.id,
        content_id=job.content_id,
        source_key=job.source_key,
        status=job.status,
        attempts=job.attempts,
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
        content_title=content_title,
        content_type=content_type,
        content_slug=content_slug,
        series_id=series_id,
        series_title=series_title,
        season_number=season_number,
        episode_number=episode_number,
    )


def _transcode_jobs_select():
    return (
        select(
            TranscodeJob,
            Content.title.label("content_title"),
            Content.type.label("content_type"),
            Content.slug.label("content_slug"),
            Content.series_id.label("series_id"),
            Series.title.label("series_title"),
            Content.season_number.label("season_number"),
            Content.episode_number.label("episode_number"),
        )
        .outerjoin(Content, Content.id == TranscodeJob.content_id)
        .outerjoin(Series, Series.id == Content.series_id)
    )


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


class RevenueTimelinePoint(BaseModel):
    date: date
    revenue_usd: Decimal
    payment_count: int


class RevenueTimelineRead(BaseModel):
    days: int
    date_from: date | None = None
    date_to: date | None = None
    period_revenue_usd: Decimal
    all_time_revenue_usd: Decimal
    succeeded_payments: int
    points: list[RevenueTimelinePoint]


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


@router.get("/revenue-timeline", response_model=RevenueTimelineRead)
async def get_revenue_timeline(
    db: DBSession,
    _: AdminUser,
    days: int = Query(30, ge=7, le=90),
    date_from: str | None = Query(
        default=None,
        description="Include revenue on or after this date (YYYY-MM-DD)",
    ),
    date_to: str | None = Query(
        default=None,
        description="Include revenue on or before this date (YYYY-MM-DD)",
    ),
):
    now = datetime.now(timezone.utc)
    today = now.date()

    parsed_from: date | None = None
    parsed_to: date | None = None

    if date_from:
        parsed_from = _parse_filter_date(date_from, "date_from")
    if date_to:
        parsed_to = _parse_filter_date(date_to, "date_to")

    if parsed_from and parsed_to and parsed_from > parsed_to:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")

    if parsed_from or parsed_to:
        end_date = parsed_to or today
        start_date = parsed_from or (end_date - timedelta(days=days - 1))
    else:
        end_date = today
        start_date = (now - timedelta(days=days - 1)).date()

    if end_date > today:
        end_date = today
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")

    range_days = (end_date - start_date).days + 1
    if range_days > 366:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 366 days")

    since = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    until = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    revenue_timestamp = func.coalesce(PaymentIntent.resolved_at, PaymentIntent.created_at)

    rows = (
        await db.execute(
            select(
                func.date(revenue_timestamp).label("day"),
                func.coalesce(func.sum(PaymentIntent.amount_usd), Decimal("0")).label("revenue_usd"),
                func.count(PaymentIntent.intent_id).label("payment_count"),
            )
            .where(
                PaymentIntent.status == "succeeded",
                revenue_timestamp >= since,
                revenue_timestamp <= until,
            )
            .group_by(func.date(revenue_timestamp))
            .order_by(func.date(revenue_timestamp))
        )
    ).all()

    by_date = {row.day: row for row in rows}
    points: list[RevenueTimelinePoint] = []
    period_revenue = Decimal("0")
    succeeded_payments = 0
    cursor = start_date
    while cursor <= end_date:
        row = by_date.get(cursor)
        revenue = row.revenue_usd if row else Decimal("0")
        count = row.payment_count if row else 0
        points.append(
            RevenueTimelinePoint(
                date=cursor,
                revenue_usd=revenue,
                payment_count=count,
            )
        )
        period_revenue += revenue
        succeeded_payments += count
        cursor += timedelta(days=1)

    all_time_revenue = await db.scalar(
        select(
            func.coalesce(
                func.sum(PaymentIntent.amount_usd).filter(PaymentIntent.status == "succeeded"),
                Decimal("0"),
            )
        )
    )

    return RevenueTimelineRead(
        days=range_days,
        date_from=start_date,
        date_to=end_date,
        period_revenue_usd=period_revenue,
        all_time_revenue_usd=all_time_revenue or Decimal("0"),
        succeeded_payments=succeeded_payments,
        points=points,
    )


@router.get("/reports/top-titles", response_model=PaginatedResponse[TopTitleReportRead])
async def list_top_titles(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
    content_type: str | None = Query(
        None,
        description="Filter by content type, e.g. single for movies only",
    ),
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
    )
    if content_type:
        stmt = stmt.where(Content.type == content_type)

    if content_type == "single":
        stmt = stmt.order_by(
            func.coalesce(purchase_stats.c.purchase_count, 0).desc(),
            func.coalesce(watch_stats.c.watch_count, 0).desc(),
            func.coalesce(purchase_stats.c.revenue_usd, Decimal("0")).desc(),
            Content.created_at.desc(),
        )
    else:
        stmt = stmt.order_by(
            func.coalesce(purchase_stats.c.revenue_usd, Decimal("0")).desc(),
            func.coalesce(purchase_stats.c.purchase_count, 0).desc(),
            func.coalesce(watch_stats.c.watch_count, 0).desc(),
            Content.created_at.desc(),
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


async def _watch_counts_for_content(
    db: DBSession, content_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not content_ids:
        return {}
    result = await db.execute(
        select(
            WatchProgress.content_id,
            func.count(WatchProgress.user_id).label("watch_count"),
        )
        .where(WatchProgress.content_id.in_(content_ids))
        .group_by(WatchProgress.content_id)
    )
    return {row.content_id: int(row.watch_count) for row in result.all()}


class AdminMovieCreate(BaseModel):
    title: str
    description: str | None = None
    genres: list[str] = []
    release_year: int | None = None
    rating: Decimal | None = None
    runtime_minutes: int | None = Field(default=None, gt=0)
    price_usd: Decimal = Decimal("0")
    trailer_url: str | None = None

    @field_validator("title")
    @classmethod
    def title_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title is required")
        return value

    @field_validator("price_usd")
    @classmethod
    def check_price_usd(cls, value: Decimal) -> Decimal:
        return validate_usd_price(value)


@router.post("/movies", response_model=ContentRead, status_code=201)
async def create_admin_movie_draft(data: AdminMovieCreate, db: DBSession, _: AdminUser):
    """Create a movie record without video (draft). Upload assets later from movie edit."""
    slug = await _unique_slug(data.title, db)
    movie = Content(
        id=uuid.uuid4(),
        type="single",
        slug=slug,
        title=data.title,
        description=data.description,
        genres=data.genres,
        release_year=data.release_year,
        rating=data.rating,
        price_usd=data.price_usd,
        trailer_url=data.trailer_url,
        status="draft",
        is_published=False,
        transcode_status="pending",
    )
    apply_runtime_minutes(movie, data.runtime_minutes)
    db.add(movie)
    await db.commit()
    await db.refresh(movie)
    return movie


@router.get("/movies", response_model=PaginatedResponse[AdminContentRead])
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
    watch_counts = await _watch_counts_for_content(db, [m.id for m in items])
    return build_paginated_response(
        [
            AdminContentRead(
                **ContentRead.model_validate(m).model_dump(),
                watch_count=watch_counts.get(m.id, 0),
            )
            for m in items
        ],
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
    runtime_minutes = updates.pop("runtime_minutes", None)
    if "status" in updates:
        if updates["status"] not in _VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUSES)}")
        updates["is_published"] = updates["status"] == "published"

    for field, value in updates.items():
        setattr(movie, field, value)

    if "runtime_minutes" in data.model_fields_set:
        if runtime_minutes is None:
            movie.duration_seconds = None
            movie.runtime = None
        else:
            apply_runtime_minutes(movie, runtime_minutes)

    if movie.status == "published":
        await ensure_movie_publishable(db, movie)

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

    source_key: str | None = None
    video_upload_url: str | None = None
    poster_key: str | None = None
    poster_upload_url: str | None = None

    if data.video_content_type:
        source_key = r2_keys.movie_source_key(movie.slug)
        video_upload_url = storage.generate_presigned_upload_url(
            source_key,
            data.video_content_type,
        )

    if data.poster_content_type:
        poster_key = r2_keys.movie_poster_key(movie.slug, data.poster_content_type)
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
        if data.source_key != r2_keys.movie_source_key(movie.slug):
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
        if not r2_keys.is_movie_asset_key(movie.slug, data.poster_key):
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
    await delete_content_dependencies(db, movie_id)
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
    stmt = _transcode_jobs_select().order_by(TranscodeJob.created_at.desc())
    if status:
        stmt = stmt.where(TranscodeJob.status == status)
    rows, total = await paginate_query(
        db,
        stmt,
        page=pagination.page,
        page_size=pagination.page_size,
        scalar=False,
    )
    return build_paginated_response(
        [_transcode_job_row_to_read(row) for row in rows],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/transcode-jobs/progress")
async def admin_transcode_jobs_progress(_: AdminUser):
    from app.services.transcode_client import fetch_jobs_progress

    return await fetch_jobs_progress()


@router.post("/transcode-jobs/{job_id}/cancel")
async def admin_cancel_transcode_job(job_id: uuid.UUID, _: AdminUser):
    from app.services.transcode_client import cancel_job

    return await cancel_job(str(job_id))


@router.post("/transcode-jobs/{job_id}/retry", response_model=TranscodeJobRead)
async def retry_transcode_job(job_id: uuid.UUID, db: DBSession, _: AdminUser):
    result = await db.execute(select(TranscodeJob).where(TranscodeJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Transcode job not found")
    job.status = "queued"
    job.error = None
    await db.commit()
    row = (
        await db.execute(_transcode_jobs_select().where(TranscodeJob.id == job_id))
    ).one()
    return _transcode_job_row_to_read(row)


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


def _parse_filter_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be YYYY-MM-DD",
        ) from exc


@router.get("/payments", response_model=PaginatedResponse[AdminPaymentRead])
async def list_admin_payments(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
    search: str | None = Query(
        default=None,
        description="Filter by user full name or email (case-insensitive)",
    ),
    date_from: str | None = Query(
        default=None,
        description="Include transactions on or after this date (YYYY-MM-DD)",
    ),
    date_to: str | None = Query(
        default=None,
        description="Include transactions on or before this date (YYYY-MM-DD)",
    ),
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

    if search and (term := search.strip()):
        pattern = f"%{term}%"
        stmt = stmt.where(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
            )
        )

    parsed_from: date | None = None
    parsed_to: date | None = None

    if date_from:
        parsed_from = _parse_filter_date(date_from, "date_from")
        start = datetime.combine(parsed_from, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(PaymentIntent.created_at >= start)

    if date_to:
        parsed_to = _parse_filter_date(date_to, "date_to")
        end = datetime.combine(parsed_to, time.max, tzinfo=timezone.utc)
        stmt = stmt.where(PaymentIntent.created_at <= end)

    if parsed_from and parsed_to and parsed_from > parsed_to:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
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


@router.get("/comments", response_model=PaginatedResponse[CommentRead])
async def list_admin_comments(
    content_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
):
    await ensure_commentable_movie(db, content_id, allow_unpublished=True)

    stmt = (
        select(Comment, User)
        .join(User, Comment.user_id == User.id)
        .where(
            Comment.content_id == content_id,
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at.desc())
    )
    rows, total = await paginate_query(
        db,
        stmt,
        page=pagination.page,
        page_size=pagination.page_size,
        scalar=False,
    )
    items = [
        to_comment_read(comment, author)
        for comment, author in rows
    ]
    return build_paginated_response(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.patch("/comments/{comment_id}", response_model=CommentRead)
async def update_admin_comment(
    comment_id: uuid.UUID,
    data: CommentUpdate,
    db: DBSession,
    _: AdminUser,
):
    comment = await get_comment_or_404(db, comment_id)
    await ensure_commentable_movie(db, comment.content_id, allow_unpublished=True)

    author_result = await db.execute(select(User).where(User.id == comment.user_id))
    author = author_result.scalar_one()
    comment = await update_comment_body(db, comment, data.body)
    return to_comment_read(comment, author)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_admin_comment(
    comment_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    comment = await get_comment_or_404(db, comment_id)
    await soft_delete_comment(db, comment)
