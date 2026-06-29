from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.models.hero_featured_item import HeroFeaturedItem
from app.models.series import Series
from app.schemas.hero_featured import HeroFeaturedItemRead, HeroFeaturedSlideRead


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def list_active_hero_items(
    db: AsyncSession,
    *,
    placement: str = "home",
) -> list[HeroFeaturedItem]:
    now = _utc_now()
    stmt = (
        select(HeroFeaturedItem)
        .where(
            HeroFeaturedItem.placement == placement,
            HeroFeaturedItem.is_active.is_(True),
            or_(HeroFeaturedItem.starts_at.is_(None), HeroFeaturedItem.starts_at <= now),
            or_(HeroFeaturedItem.ends_at.is_(None), HeroFeaturedItem.ends_at >= now),
        )
        .order_by(HeroFeaturedItem.sort_order.asc(), HeroFeaturedItem.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def resolve_hero_slides(
    db: AsyncSession,
    *,
    placement: str = "home",
) -> list[HeroFeaturedSlideRead]:
    items = await list_active_hero_items(db, placement=placement)
    if not items:
        return []

    # Batch-load all referenced movies and series in two queries (not per-item).
    movie_ids = [item.content_id for item in items if item.content_type == "movie"]
    series_ids = [item.content_id for item in items if item.content_type == "series"]

    movies_by_id: dict[UUID, Content] = {}
    series_by_id: dict[UUID, Series] = {}

    if movie_ids:
        result = await db.execute(
            select(Content).where(
                Content.id.in_(movie_ids),
                Content.type == "single",
                Content.is_published.is_(True),
            )
        )
        movies_by_id = {row.id: row for row in result.scalars().all()}

    if series_ids:
        result = await db.execute(
            select(Series).where(
                Series.id.in_(series_ids),
                Series.is_published.is_(True),
            )
        )
        series_by_id = {row.id: row for row in result.scalars().all()}

    slides: list[HeroFeaturedSlideRead] = []
    for item in items:
        slide = _build_slide(item, movies_by_id, series_by_id)
        if slide:
            slides.append(slide)
    return slides


def _build_slide(
    item: HeroFeaturedItem,
    movies_by_id: dict[UUID, Content],
    series_by_id: dict[UUID, Series],
) -> HeroFeaturedSlideRead | None:
    if item.content_type == "movie":
        movie = movies_by_id.get(item.content_id)
        if not movie:
            return None
        return HeroFeaturedSlideRead(
            id=movie.id,
            content_type="movie",
            title=movie.title,
            slug=movie.slug,
            description=movie.description,
            genres=movie.genres or [],
            release_year=movie.release_year,
            rating=movie.rating,
            runtime=movie.runtime,
            poster_key=movie.poster_key,
            banner_key=movie.banner_key,
            watch_href=f"/watch?slug={movie.slug}",
            sort_order=item.sort_order,
        )

    if item.content_type == "series":
        series = series_by_id.get(item.content_id)
        if not series:
            return None
        return HeroFeaturedSlideRead(
            id=series.id,
            content_type="series",
            title=series.title,
            slug=series.slug,
            description=series.description,
            genres=series.genres or [],
            release_year=series.release_year,
            rating=series.rating,
            runtime="Series",
            poster_key=series.poster_key,
            banner_key=series.banner_key,
            watch_href=f"/watch/series/{series.slug}/1/1",
            sort_order=item.sort_order,
        )

    return None


async def enrich_admin_hero_items(
    db: AsyncSession,
    items: list[HeroFeaturedItem],
) -> list[HeroFeaturedItemRead]:
    if not items:
        return []

    movie_ids = [item.content_id for item in items if item.content_type == "movie"]
    series_ids = [item.content_id for item in items if item.content_type == "series"]

    movies_by_id: dict[UUID, Content] = {}
    series_by_id: dict[UUID, Series] = {}

    if movie_ids:
        result = await db.execute(select(Content).where(Content.id.in_(movie_ids)))
        movies_by_id = {row.id: row for row in result.scalars().all()}

    if series_ids:
        result = await db.execute(select(Series).where(Series.id.in_(series_ids)))
        series_by_id = {row.id: row for row in result.scalars().all()}

    enriched: list[HeroFeaturedItemRead] = []
    for item in items:
        read = HeroFeaturedItemRead.model_validate(item)
        if item.content_type == "movie":
            movie = movies_by_id.get(item.content_id)
            if movie:
                read.content_title = movie.title
                read.content_slug = movie.slug
                read.poster_key = movie.poster_key
        elif item.content_type == "series":
            series = series_by_id.get(item.content_id)
            if series:
                read.content_title = series.title
                read.content_slug = series.slug
                read.poster_key = series.poster_key
        enriched.append(read)

    return enriched


async def validate_hero_content(
    db: AsyncSession,
    *,
    content_type: str,
    content_id: UUID,
) -> None:
    if content_type == "movie":
        result = await db.execute(
            select(Content.id).where(
                Content.id == content_id,
                Content.type == "single",
            )
        )
        if not result.scalar_one_or_none():
            raise ValueError("Movie not found")
        return

    if content_type == "series":
        result = await db.execute(select(Series.id).where(Series.id == content_id))
        if not result.scalar_one_or_none():
            raise ValueError("Series not found")
        return

    raise ValueError("content_type must be movie or series")
