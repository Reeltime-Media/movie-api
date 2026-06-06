"""Authenticated library endpoints for the movie client."""

from fastapi import APIRouter
from sqlalchemy import select

from app.dependencies import CurrentUser, DBSession
from app.models.content import Content
from app.models.purchase import Purchase
from app.schemas.content import ContentListItemRead

router = APIRouter(prefix="/library", tags=["library"])


@router.get("/owned", response_model=list[ContentListItemRead])
async def list_owned_movies(db: DBSession, current_user: CurrentUser):
    """Published movies the user has purchased."""
    result = await db.execute(
        select(Content)
        .join(Purchase, Purchase.content_id == Content.id)
        .where(
            Purchase.user_id == current_user.id,
            Content.type == "single",
            Content.is_published.is_(True),
        )
        .order_by(Purchase.purchased_at.desc())
    )
    return [ContentListItemRead.model_validate(row) for row in result.scalars().all()]
