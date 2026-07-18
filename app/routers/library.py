"""Library endpoints for the movie client — owned movies resolve either a
logged-in user_id or an anonymous guest_id cookie."""

from fastapi import APIRouter, Request
from sqlalchemy import false, select

from app.core.guest import get_guest_id
from app.dependencies import DBSession, OptionalUser
from app.models.content import Content
from app.models.purchase import Purchase
from app.schemas.content import ContentListItemRead

router = APIRouter(prefix="/library", tags=["library"])


@router.get("/owned", response_model=list[ContentListItemRead])
async def list_owned_movies(db: DBSession, request: Request, user: OptionalUser):
    """Published movies the user (or guest) has purchased."""
    guest_id = get_guest_id(request)
    identity_filter = (
        Purchase.user_id == user.id
        if user
        else (Purchase.guest_id == guest_id if guest_id else false())
    )
    result = await db.execute(
        select(Content)
        .join(Purchase, Purchase.content_id == Content.id)
        .where(
            identity_filter,
            Content.type == "single",
            Content.is_published.is_(True),
        )
        .order_by(Purchase.purchased_at.desc())
    )
    return [ContentListItemRead.model_validate(row) for row in result.scalars().all()]
