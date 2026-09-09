import uuid
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import or_, select

from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.payment_intent import PaymentIntent
from app.models.user import User
from app.schemas.admin import AdminPaymentFulfillRead, AdminPaymentRead
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services.admin.dates import parse_filter_date
from app.services.pagination import paginate_query
from app.services.payment_fulfillment import fulfill_payment_intent

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
    status: str | None = Query(
        default=None,
        description="Filter by payment status (pending, succeeded, failed)",
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
        .outerjoin(User, User.id == PaymentIntent.user_id)
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

    if status and (status_term := status.strip().lower()):
        allowed = {"pending", "succeeded", "failed"}
        if status_term not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of: {', '.join(sorted(allowed))}",
            )
        stmt = stmt.where(PaymentIntent.status == status_term)

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
                user_email=email or "Guest (no account)",
                user_full_name=full_name,
                kind=intent.kind,
                method=intent.method,
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


@router.post(
    "/payments/{intent_id}/fulfill",
    response_model=AdminPaymentFulfillRead,
)
async def admin_fulfill_payment(
    intent_id: str,
    db: DBSession,
    admin: AdminUser,
):
    """Mark a pending payment succeeded after ops verifies the bank/Bakong receipt.

    Does not call NBC. Idempotent if already succeeded.
    """
    _ = admin
    result = await db.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
    )
    intent = result.scalar_one_or_none()
    if not intent:
        raise NotFoundError("Payment intent not found")
    if intent.status not in ("pending", "succeeded"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot fulfill intent in status={intent.status}",
        )

    await fulfill_payment_intent(db, intent, bank="manual_bakong")
    await db.commit()
    await db.refresh(intent)
    return AdminPaymentFulfillRead(
        intent_id=intent.intent_id,
        order_id=intent.order_id,
        status=intent.status,
        resolved_at=intent.resolved_at,
    )
