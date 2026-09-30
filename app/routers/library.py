"""Library endpoints for the movie client — owned movies resolve either a
logged-in user_id or an anonymous guest_id cookie."""

from fastapi import APIRouter, Request
from sqlalchemy import false, select

from app.core.guest import get_guest_id
from app.dependencies import DBSession, OptionalUser
from app.models.content import Content
from app.models.purchase import Purchase
from app.schemas.content import ContentListItemRead
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services.catalog_columns import content_list_load_options
from app.services.pagination import paginate_query

router = APIRouter(prefix="/library", tags=["library"])


@router.get("/owned", response_model=PaginatedResponse[ContentListItemRead])
async def list_owned_movies(
    db: DBSession,
    request: Request,
    user: OptionalUser,
    pagination: PaginationDep,
):
    """Published movies the user (or guest) has purchased."""
    guest_id = get_guest_id(request)
    identity_filter = (
        Purchase.user_id == user.id
        if user
        else (Purchase.guest_id == guest_id if guest_id else false())
    )
    stmt = (
        select(Content)
        .options(content_list_load_options())
        .join(Purchase, Purchase.content_id == Content.id)
        .where(
            identity_filter,
            Content.type == "single",
            Content.is_published.is_(True),
        )
        .order_by(Purchase.purchased_at.desc())
    )
    items, total = await paginate_query(
        db,
        stmt,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return build_paginated_response(
        [ContentListItemRead.model_validate(row) for row in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
