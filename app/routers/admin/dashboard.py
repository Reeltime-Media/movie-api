from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.dependencies import AdminUser, DBSession
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.series import Series
from app.models.user import User
from app.models.watch_progress import WatchProgress
from app.schemas.admin import (
    DashboardContentSummary,
    DashboardPaymentSummary,
    DashboardSummaryRead,
    DashboardTranscodeSummary,
    DashboardUserSummary,
    RevenueTimelinePoint,
    RevenueTimelineRead,
    TopTitleReportRead,
)
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services.admin.dates import parse_filter_date
from app.services.pagination import paginate_query

router = APIRouter()


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
        parsed_from = parse_filter_date(date_from, "date_from")
    if date_to:
        parsed_to = parse_filter_date(date_to, "date_to")

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
