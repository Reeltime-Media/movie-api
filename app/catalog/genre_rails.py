"""Admin-curated home genre rails (Horror, Action, …)."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.models.genre_rail_item import GenreRailItem
from app.schemas.content import ContentListItemRead
from app.schemas.genre_rail import GENRE_RAIL_MAX_PER_GENRE, GenreRailItemRead, GenreRailRead


def _normalize_genre(name: str) -> str:
    return " ".join(name.strip().split())


async def enrich_admin_genre_rail_items(
    db: AsyncSession, items: list[GenreRailItem]
) -> list[GenreRailItemRead]:
    if not items:
        return []
    ids = [item.content_id for item in items]
    result = await db.execute(select(Content).where(Content.id.in_(ids)))
    movies_by_id = {movie.id: movie for movie in result.scalars().all()}

    enriched: list[GenreRailItemRead] = []
    for item in items:
        read = GenreRailItemRead.model_validate(item)
        movie = movies_by_id.get(item.content_id)
        if movie:
            read.content_title = movie.title
            read.content_slug = movie.slug
            read.poster_key = movie.poster_key
        enriched.append(read)
    return enriched


async def validate_genre_rail_add(
    db: AsyncSession, genre_name: str, content_id: UUID
) -> str:
    genre = _normalize_genre(genre_name)
    if not genre:
        raise ValueError("Genre name is required")

    result = await db.execute(
        select(Content.id).where(Content.id == content_id, Content.type == "single")
    )
    if not result.scalar_one_or_none():
        raise ValueError("Movie not found")

    result = await db.execute(
        select(GenreRailItem.id).where(
            GenreRailItem.genre_name == genre,
            GenreRailItem.content_id == content_id,
        )
    )
    if result.scalar_one_or_none():
        raise ValueError("This movie is already in that genre rail")

    result = await db.execute(
        select(func.count())
        .select_from(GenreRailItem)
        .where(GenreRailItem.genre_name == genre)
    )
    if (result.scalar() or 0) >= GENRE_RAIL_MAX_PER_GENRE:
        raise ValueError(
            f"Each genre rail is limited to {GENRE_RAIL_MAX_PER_GENRE} titles"
        )
    return genre


async def resolve_genre_rails(db: AsyncSession) -> list[GenreRailRead]:
    """Published movies grouped by genre, each rail in admin sort order."""
    from app.catalog.columns import content_list_load_options

    result = await db.execute(
        select(GenreRailItem).order_by(
            GenreRailItem.genre_name.asc(),
            GenreRailItem.sort_order.asc(),
            GenreRailItem.created_at.desc(),
        )
    )
    items = list(result.scalars().all())
    if not items:
        return []

    content_ids = list({item.content_id for item in items})
    movies_result = await db.execute(
        select(Content)
        .options(content_list_load_options())
        .where(
            Content.id.in_(content_ids),
            Content.type == "single",
            Content.is_published.is_(True),
        )
    )
    movies_by_id = {movie.id: movie for movie in movies_result.scalars().all()}

    rails: dict[str, list[ContentListItemRead]] = {}
    for item in items:
        movie = movies_by_id.get(item.content_id)
        if not movie:
            continue
        rail = rails.setdefault(item.genre_name, [])
        if len(rail) >= GENRE_RAIL_MAX_PER_GENRE:
            continue
        rail.append(ContentListItemRead.model_validate(movie))

    return [GenreRailRead(genre=genre, movies=movies) for genre, movies in rails.items() if movies]
