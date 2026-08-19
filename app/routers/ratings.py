import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.dependencies import CurrentUser, DBSession
from app.models.rating import Rating
from app.schemas.rating import RatingRead, RatingUpsert, RatingWriteResult
from app.services.ratings import assert_rateable_movie, upsert_rating

router = APIRouter(prefix="/ratings", tags=["ratings"])


@router.get("/{content_id}/me", response_model=RatingRead)
async def get_my_rating(content_id: uuid.UUID, db: DBSession, current_user: CurrentUser):
    result = await db.execute(
        select(Rating).where(
            Rating.user_id == current_user.id,
            Rating.content_id == content_id,
        )
    )
    rating = result.scalar_one_or_none()
    if not rating:
        raise NotFoundError("No rating yet")
    return rating


@router.put("/{content_id}", response_model=RatingWriteResult)
async def rate_movie(
    content_id: uuid.UUID,
    data: RatingUpsert,
    db: DBSession,
    current_user: CurrentUser,
):
    content = await assert_rateable_movie(db, content_id)
    rating, count = await upsert_rating(
        db, content=content, user_id=current_user.id, value=data.value
    )
    return RatingWriteResult(
        content_id=content_id,
        value=rating.value,
        content_rating=content.rating,
        rating_count=count,
    )
