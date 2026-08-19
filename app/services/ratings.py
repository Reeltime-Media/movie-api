import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.content import Content
from app.models.rating import Rating


async def assert_rateable_movie(db: AsyncSession, content_id: uuid.UUID) -> Content:
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content or content.type != "single" or not content.is_published:
        raise NotFoundError("Movie not found")
    return content


async def _recompute_content_rating(db: AsyncSession, content: Content) -> int:
    result = await db.execute(
        select(func.avg(Rating.value), func.count(Rating.value)).where(
            Rating.content_id == content.id
        )
    )
    avg_value, count = result.one()
    if count:
        # Star average (1-5) mapped onto the existing 0-10 display scale.
        content.rating = (Decimal(str(avg_value)) * 2).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    await db.commit()
    return int(count)


async def upsert_rating(
    db: AsyncSession, *, content: Content, user_id: uuid.UUID, value: int
) -> tuple[Rating, int]:
    result = await db.execute(
        select(Rating).where(
            Rating.user_id == user_id,
            Rating.content_id == content.id,
        )
    )
    rating = result.scalar_one_or_none()
    if rating:
        rating.value = value
    else:
        rating = Rating(user_id=user_id, content_id=content.id, value=value)
        db.add(rating)
    await db.commit()
    await db.refresh(rating)

    count = await _recompute_content_rating(db, content)
    await db.refresh(content)
    return rating, count
