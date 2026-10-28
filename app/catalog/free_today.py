"""Admin-curated "Free movies today" picks and their entitlement override."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.models.free_today_item import FreeTodayItem
from app.models.home_section import HomeSection, HomeSectionItem
from app.schemas.free_today import FREE_TODAY_MAX, FreeTodayItemRead


async def _home_free_today_ids(db: AsyncSession) -> set[UUID]:
    from app.catalog.home_sections import free_today_content_ids_from_sections

    try:
        return await free_today_content_ids_from_sections(db)
    except Exception:
        # Table may not exist before migration 0057.
        return set()


async def content_ids_free_today(db: AsyncSession) -> set[UUID]:
    legacy = await db.execute(select(FreeTodayItem.content_id))
    ids = set(legacy.scalars().all())
    ids |= await _home_free_today_ids(db)
    return ids


async def is_free_today(db: AsyncSession, content_id: UUID) -> bool:
    home_ids = await _home_free_today_ids(db)
    if content_id in home_ids:
        return True
    result = await db.execute(
        select(FreeTodayItem.id).where(FreeTodayItem.content_id == content_id)
    )
    return result.scalar_one_or_none() is not None


async def resolve_free_today_movies(db: AsyncSession) -> list[Content]:
    """Published movies currently listed, in rail order.

    Prefer a visible home_sections free_today rail when it has items; else legacy table.
    """
    from app.catalog.columns import content_list_load_options

    section_result = await db.execute(
        select(HomeSection)
        .where(HomeSection.type == "free_today", HomeSection.is_visible.is_(True))
        .order_by(HomeSection.sort_order.asc())
        .limit(1)
    )
    section = section_result.scalar_one_or_none()
    if section:
        item_count = await db.execute(
            select(func.count())
            .select_from(HomeSectionItem)
            .where(
                HomeSectionItem.section_id == section.id,
                HomeSectionItem.item_kind == "movie",
            )
        )
        if int(item_count.scalar() or 0) > 0:
            stmt = (
                select(Content)
                .options(content_list_load_options())
                .join(
                    HomeSectionItem,
                    HomeSectionItem.ref_id == Content.id,
                )
                .where(
                    HomeSectionItem.section_id == section.id,
                    HomeSectionItem.item_kind == "movie",
                    Content.type == "single",
                    Content.is_published.is_(True),
                )
                .order_by(
                    HomeSectionItem.sort_order.asc(),
                    HomeSectionItem.created_at.desc(),
                )
                .limit(FREE_TODAY_MAX)
            )
            result = await db.execute(stmt)
            return list(result.scalars().all())

    stmt = (
        select(Content)
        .options(content_list_load_options())
        .join(FreeTodayItem, FreeTodayItem.content_id == Content.id)
        .where(Content.type == "single", Content.is_published.is_(True))
        .order_by(FreeTodayItem.sort_order.asc(), FreeTodayItem.created_at.desc())
        .limit(FREE_TODAY_MAX)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def enrich_admin_free_today(
    db: AsyncSession, items: list[FreeTodayItem]
) -> list[FreeTodayItemRead]:
    if not items:
        return []
    ids = [item.content_id for item in items]
    result = await db.execute(select(Content).where(Content.id.in_(ids)))
    movies_by_id = {movie.id: movie for movie in result.scalars().all()}

    enriched: list[FreeTodayItemRead] = []
    for item in items:
        read = FreeTodayItemRead.model_validate(item)
        movie = movies_by_id.get(item.content_id)
        if movie:
            read.content_title = movie.title
            read.content_slug = movie.slug
            read.poster_key = movie.poster_key
        enriched.append(read)
    return enriched


async def validate_free_today_add(db: AsyncSession, content_id: UUID) -> None:
    result = await db.execute(
        select(Content.id).where(Content.id == content_id, Content.type == "single")
    )
    if not result.scalar_one_or_none():
        raise ValueError("Movie not found")

    result = await db.execute(
        select(FreeTodayItem.id).where(FreeTodayItem.content_id == content_id)
    )
    if result.scalar_one_or_none():
        raise ValueError("This movie is already in Free movies today")

    result = await db.execute(select(func.count()).select_from(FreeTodayItem))
    if (result.scalar() or 0) >= FREE_TODAY_MAX:
        raise ValueError(f"Free movies today is limited to {FREE_TODAY_MAX} titles")
