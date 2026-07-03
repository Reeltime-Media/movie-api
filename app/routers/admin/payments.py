import uuid
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.dependencies import AdminUser, DBSession
from app.models.payment_intent import PaymentIntent
from app.models.user import User
from app.schemas.admin import AdminPaymentRead
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services.admin.dates import parse_filter_date
from app.services.pagination import paginate_query

router = APIRouter()


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
        parsed_from = parse_filter_date(date_from, "date_from")
        start = datetime.combine(parsed_from, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(PaymentIntent.created_at >= start)

    if date_to:
        parsed_to = parse_filter_date(date_to, "date_to")
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
