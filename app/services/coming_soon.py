"""Admin-curated Coming Soon home rail (poster-first, may be unpublished)."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coming_soon_item import ComingSoonItem
from app.models.content import Content
from app.schemas.coming_soon import COMING_SOON_MAX, ComingSoonItemRead


async def is_coming_soon(db: AsyncSession, content_id: UUID) -> bool:
    result = await db.execute(
        select(ComingSoonItem.id).where(ComingSoonItem.content_id == content_id)
    )
    return result.scalar_one_or_none() is not None


async def resolve_coming_soon_movies(db: AsyncSession) -> list[Content]:
    """Movies on the Coming Soon rail (published or not), poster required."""
    stmt = (
        select(Content)
        .join(ComingSoonItem, ComingSoonItem.content_id == Content.id)
        .where(
            Content.type == "single",
            Content.poster_key.is_not(None),
            Content.poster_key != "",
        )
        .order_by(ComingSoonItem.sort_order.asc(), ComingSoonItem.created_at.desc())
        .limit(COMING_SOON_MAX)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def enrich_admin_coming_soon(
    db: AsyncSession, items: list[ComingSoonItem]
) -> list[ComingSoonItemRead]:
    if not items:
        return []
    ids = [item.content_id for item in items]
    result = await db.execute(select(Content).where(Content.id.in_(ids)))
    movies_by_id = {movie.id: movie for movie in result.scalars().all()}

    enriched: list[ComingSoonItemRead] = []
    for item in items:
        read = ComingSoonItemRead.model_validate(item)
        movie = movies_by_id.get(item.content_id)
        if movie:
            read.content_title = movie.title
            read.content_slug = movie.slug
            read.poster_key = movie.poster_key
            read.is_published = movie.is_published
        enriched.append(read)
    return enriched


async def validate_coming_soon_add(db: AsyncSession, content_id: UUID) -> None:
    result = await db.execute(
        select(Content).where(Content.id == content_id, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise ValueError("Movie not found")
    if not movie.poster_key:
        raise ValueError("Movie needs a poster before it can be Coming Soon")

    result = await db.execute(
        select(ComingSoonItem.id).where(ComingSoonItem.content_id == content_id)
    )
    if result.scalar_one_or_none():
        raise ValueError("This movie is already in Coming Soon")

    result = await db.execute(select(func.count()).select_from(ComingSoonItem))
    if (result.scalar() or 0) >= COMING_SOON_MAX:
        raise ValueError(f"Coming Soon is limited to {COMING_SOON_MAX} titles")
