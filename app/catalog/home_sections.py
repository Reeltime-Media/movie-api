"""Landing-page home sections builder — admin curation + public resolve."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.models.hero_featured_item import HeroFeaturedItem
from app.models.home_section import HomeSection, HomeSectionItem
from app.models.promotion_banner import PromotionBanner
from app.models.series import Series
from app.models.tv_channel import TVChannel
from app.schemas.channel import TVChannelPublicRead
from app.schemas.content import ContentListItemRead
from app.schemas.home_section import (
    ITEM_KINDS_BY_TYPE,
    SECTION_CAPS,
    SINGLETON_TYPES,
    HomeSectionAdminRead,
    HomeSectionItemRead,
    HomeSectionPublicRead,
)
from app.schemas.promotion_banner import PromotionBannerRead
from app.schemas.series import SeriesListItemRead


def _normalize_genre(name: str) -> str:
    return " ".join(name.strip().split())


async def list_sections_admin(db: AsyncSession) -> list[HomeSectionAdminRead]:
    result = await db.execute(
        select(HomeSection).order_by(HomeSection.sort_order.asc(), HomeSection.created_at.asc())
    )
    sections = list(result.scalars().all())
    if not sections:
        return []

    counts_result = await db.execute(
        select(HomeSectionItem.section_id, func.count()).group_by(HomeSectionItem.section_id)
    )
    counts = {row[0]: int(row[1]) for row in counts_result.all()}

    out: list[HomeSectionAdminRead] = []
    for section in sections:
        read = HomeSectionAdminRead.model_validate(section)
        read.item_count = counts.get(section.id, 0)
        out.append(read)
    return out


async def get_section_admin(db: AsyncSession, section_id: UUID) -> HomeSectionAdminRead | None:
    result = await db.execute(select(HomeSection).where(HomeSection.id == section_id))
    section = result.scalar_one_or_none()
    if not section:
        return None
    items = await list_section_items_admin(db, section_id)
    read = HomeSectionAdminRead.model_validate(section)
    read.item_count = len(items)
    read.items = items
    return read


async def list_section_items_admin(db: AsyncSession, section_id: UUID) -> list[HomeSectionItemRead]:
    result = await db.execute(
        select(HomeSectionItem)
        .where(HomeSectionItem.section_id == section_id)
        .order_by(HomeSectionItem.sort_order.asc(), HomeSectionItem.created_at.desc())
    )
    items = list(result.scalars().all())
    return await enrich_admin_items(db, items)


async def enrich_admin_items(
    db: AsyncSession, items: list[HomeSectionItem]
) -> list[HomeSectionItemRead]:
    if not items:
        return []

    movie_ids = [i.ref_id for i in items if i.item_kind == "movie"]
    series_ids = [i.ref_id for i in items if i.item_kind == "series"]
    channel_ids = [i.ref_id for i in items if i.item_kind == "tv_channel"]
    hero_ids = [i.ref_id for i in items if i.item_kind == "hero_slide"]
    banner_ids = [i.ref_id for i in items if i.item_kind == "banner"]

    movies: dict[UUID, Content] = {}
    series_map: dict[UUID, Series] = {}
    channels: dict[UUID, TVChannel] = {}
    heroes: dict[UUID, HeroFeaturedItem] = {}
    banners: dict[UUID, PromotionBanner] = {}

    if movie_ids:
        movie_result = await db.execute(select(Content).where(Content.id.in_(movie_ids)))
        movies = {m.id: m for m in movie_result.scalars().all()}
    if series_ids:
        series_result = await db.execute(select(Series).where(Series.id.in_(series_ids)))
        series_map = {s.id: s for s in series_result.scalars().all()}
    if channel_ids:
        channel_result = await db.execute(select(TVChannel).where(TVChannel.id.in_(channel_ids)))
        channels = {c.id: c for c in channel_result.scalars().all()}
    if hero_ids:
        hero_result = await db.execute(
            select(HeroFeaturedItem).where(HeroFeaturedItem.id.in_(hero_ids))
        )
        heroes = {h.id: h for h in hero_result.scalars().all()}
    if banner_ids:
        banner_result = await db.execute(
            select(PromotionBanner).where(PromotionBanner.id.in_(banner_ids))
        )
        banners = {b.id: b for b in banner_result.scalars().all()}

    enriched: list[HomeSectionItemRead] = []
    for item in items:
        read = HomeSectionItemRead.model_validate(item)
        if item.item_kind == "movie":
            movie = movies.get(item.ref_id)
            if movie:
                read.label = movie.title
                read.poster_key = movie.poster_key
                read.slug = movie.slug
        elif item.item_kind == "series":
            series = series_map.get(item.ref_id)
            if series:
                read.label = series.title
                read.poster_key = series.poster_key
                read.slug = series.slug
        elif item.item_kind == "tv_channel":
            channel = channels.get(item.ref_id)
            if channel:
                read.label = channel.name
                read.poster_key = channel.logo_key
                read.slug = channel.slug
        elif item.item_kind == "hero_slide":
            hero = heroes.get(item.ref_id)
            if hero:
                read.label = hero.title or hero.content_type
        elif item.item_kind == "banner":
            banner = banners.get(item.ref_id)
            if banner:
                read.label = banner.title
                read.poster_key = banner.image_key
        enriched.append(read)
    return enriched


async def validate_section_create(
    db: AsyncSession,
    *,
    section_type: str,
    genre_name: str | None,
) -> str | None:
    if section_type in SINGLETON_TYPES:
        existing = await db.execute(
            select(HomeSection.id).where(HomeSection.type == section_type).limit(1)
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"A {section_type} section already exists — edit it instead")

    normalized_genre: str | None = None
    if section_type == "genre":
        normalized_genre = _normalize_genre(genre_name or "")
        if not normalized_genre:
            raise ValueError("genre_name is required for genre sections")
        dup = await db.execute(
            select(HomeSection.id).where(
                HomeSection.type == "genre",
                func.lower(HomeSection.genre_name) == normalized_genre.lower(),
            )
        )
        if dup.scalar_one_or_none():
            raise ValueError("A rail for that genre already exists")
    return normalized_genre


async def validate_item_add(
    db: AsyncSession,
    section: HomeSection,
    *,
    item_kind: str,
    ref_id: UUID,
) -> None:
    allowed = ITEM_KINDS_BY_TYPE.get(section.type, frozenset())
    if item_kind not in allowed:
        raise ValueError(f"{section.type} sections do not accept {item_kind} items")

    if item_kind == "movie":
        r = await db.execute(
            select(Content.id).where(Content.id == ref_id, Content.type == "single")
        )
        if not r.scalar_one_or_none():
            raise ValueError("Movie not found")
    elif item_kind == "series":
        r = await db.execute(select(Series.id).where(Series.id == ref_id))
        if not r.scalar_one_or_none():
            raise ValueError("Series not found")
    elif item_kind == "tv_channel":
        r = await db.execute(select(TVChannel.id).where(TVChannel.id == ref_id))
        if not r.scalar_one_or_none():
            raise ValueError("TV channel not found")
    elif item_kind == "hero_slide":
        r = await db.execute(select(HeroFeaturedItem.id).where(HeroFeaturedItem.id == ref_id))
        if not r.scalar_one_or_none():
            raise ValueError("Hero slide not found")
    elif item_kind == "banner":
        r = await db.execute(select(PromotionBanner.id).where(PromotionBanner.id == ref_id))
        if not r.scalar_one_or_none():
            raise ValueError("Banner not found")

    dup = await db.execute(
        select(HomeSectionItem.id).where(
            HomeSectionItem.section_id == section.id,
            HomeSectionItem.item_kind == item_kind,
            HomeSectionItem.ref_id == ref_id,
        )
    )
    if dup.scalar_one_or_none():
        raise ValueError("Already on this section")

    cap = SECTION_CAPS.get(section.type)
    if cap is not None:
        count_r = await db.execute(
            select(func.count())
            .select_from(HomeSectionItem)
            .where(HomeSectionItem.section_id == section.id)
        )
        if int(count_r.scalar() or 0) >= cap:
            raise ValueError(f"This section is limited to {cap} items")


async def reorder_sections(db: AsyncSession, ids: list[UUID]) -> None:
    result = await db.execute(select(HomeSection).where(HomeSection.id.in_(ids)))
    by_id = {s.id: s for s in result.scalars().all()}
    if len(by_id) != len(set(ids)):
        raise ValueError("One or more sections were not found")
    for index, section_id in enumerate(ids):
        by_id[section_id].sort_order = index


async def free_today_content_ids_from_sections(db: AsyncSession) -> set[UUID]:
    """Content IDs on a visible free_today home section."""
    result = await db.execute(
        select(HomeSectionItem.ref_id)
        .join(HomeSection, HomeSection.id == HomeSectionItem.section_id)
        .where(
            HomeSection.type == "free_today",
            HomeSection.is_visible.is_(True),
            HomeSectionItem.item_kind == "movie",
        )
    )
    return set(result.scalars().all())


async def resolve_public_sections(db: AsyncSession) -> list[HomeSectionPublicRead]:
    result = await db.execute(
        select(HomeSection)
        .where(HomeSection.is_visible.is_(True))
        .order_by(HomeSection.sort_order.asc(), HomeSection.created_at.asc())
    )
    sections = list(result.scalars().all())
    if not sections:
        return []

    section_ids = [s.id for s in sections]
    items_result = await db.execute(
        select(HomeSectionItem)
        .where(HomeSectionItem.section_id.in_(section_ids))
        .order_by(HomeSectionItem.sort_order.asc(), HomeSectionItem.created_at.desc())
    )
    items_by_section: dict[UUID, list[HomeSectionItem]] = {}
    for item in items_result.scalars().all():
        items_by_section.setdefault(item.section_id, []).append(item)

    all_items = [i for rows in items_by_section.values() for i in rows]
    movie_ids = [i.ref_id for i in all_items if i.item_kind == "movie"]
    series_ids = [i.ref_id for i in all_items if i.item_kind == "series"]
    channel_ids = [i.ref_id for i in all_items if i.item_kind == "tv_channel"]
    hero_ids = [i.ref_id for i in all_items if i.item_kind == "hero_slide"]
    banner_ids = [i.ref_id for i in all_items if i.item_kind == "banner"]

    movies_by_id: dict[UUID, Content] = {}
    series_by_id: dict[UUID, Series] = {}
    channels_by_id: dict[UUID, TVChannel] = {}
    heroes_by_id: dict[UUID, HeroFeaturedItem] = {}
    banners_by_id: dict[UUID, PromotionBanner] = {}

    if movie_ids:
        from app.catalog.columns import content_list_load_options

        movies_result = await db.execute(
            select(Content)
            .options(content_list_load_options())
            .where(
                Content.id.in_(movie_ids),
                Content.type == "single",
                Content.is_published.is_(True),
            )
        )
        movies_by_id = {m.id: m for m in movies_result.scalars().all()}

    if series_ids:
        from app.catalog.columns import series_list_load_options

        series_result = await db.execute(
            select(Series)
            .options(series_list_load_options())
            .where(Series.id.in_(series_ids), Series.is_published.is_(True))
        )
        series_by_id = {s.id: s for s in series_result.scalars().all()}

    if channel_ids:
        channels_result = await db.execute(
            select(TVChannel).where(
                TVChannel.id.in_(channel_ids),
                TVChannel.is_published.is_(True),
            )
        )
        channels_by_id = {c.id: c for c in channels_result.scalars().all()}

    if hero_ids:
        heroes_result = await db.execute(
            select(HeroFeaturedItem).where(HeroFeaturedItem.id.in_(hero_ids))
        )
        heroes_by_id = {h.id: h for h in heroes_result.scalars().all()}

    if banner_ids:
        banners_result = await db.execute(
            select(PromotionBanner).where(PromotionBanner.id.in_(banner_ids))
        )
        banners_by_id = {b.id: b for b in banners_result.scalars().all()}

    # Hero slides need movie/series batch for _build_slide when resolving linked heroes.
    from app.catalog.hero_featured import _build_slide

    hero_movie_ids = [
        h.content_id for h in heroes_by_id.values() if h.content_type == "movie" and h.content_id
    ]
    hero_series_ids = [
        h.content_id for h in heroes_by_id.values() if h.content_type == "series" and h.content_id
    ]
    hero_movies: dict[UUID, Content] = {}
    hero_series: dict[UUID, Series] = {}
    if hero_movie_ids:
        from app.catalog.columns import content_list_load_options

        hero_movies_result = await db.execute(
            select(Content)
            .options(content_list_load_options())
            .where(
                Content.id.in_(hero_movie_ids),
                Content.type == "single",
                Content.is_published.is_(True),
            )
        )
        hero_movies = {m.id: m for m in hero_movies_result.scalars().all()}
    if hero_series_ids:
        from app.catalog.columns import series_hero_load_options

        hero_series_result = await db.execute(
            select(Series)
            .options(series_hero_load_options())
            .where(Series.id.in_(hero_series_ids), Series.is_published.is_(True))
        )
        hero_series = {s.id: s for s in hero_series_result.scalars().all()}

    public: list[HomeSectionPublicRead] = []
    for section in sections:
        cap = SECTION_CAPS.get(section.type)
        rows = items_by_section.get(section.id, [])
        payload = HomeSectionPublicRead(
            id=section.id,
            type=section.type,
            title=section.title,
            genre_name=section.genre_name,
            sort_order=section.sort_order,
        )

        if section.type == "plans":
            public.append(payload)
            continue

        if section.type == "hero":
            slides = []
            for item in rows:
                hero = heroes_by_id.get(item.ref_id)
                if not hero:
                    continue
                slide = _build_slide(hero, hero_movies, hero_series)
                if slide:
                    slides.append(slide)
                if cap is not None and len(slides) >= cap:
                    break
            if not slides:
                from app.catalog.hero_featured import resolve_hero_slides

                slides = await resolve_hero_slides(db, placement="home")
            payload.hero_slides = slides[: cap or len(slides)]
            public.append(payload)
            continue

        if section.type == "banners":
            banners = []
            for item in rows:
                banner = banners_by_id.get(item.ref_id)
                if not banner or not banner.is_active:
                    continue
                banners.append(PromotionBannerRead.model_validate(banner))
                if cap is not None and len(banners) >= cap:
                    break
            if not banners:
                from app.services.promotion_banners import list_active_promotion_banners

                active = await list_active_promotion_banners(db, placement="home")
                banners = [PromotionBannerRead.model_validate(b) for b in active]
            payload.banners = banners[: cap or len(banners)]
            public.append(payload)
            continue

        if section.type == "tv":
            channels = []
            for item in rows:
                channel = channels_by_id.get(item.ref_id)
                if not channel:
                    continue
                channels.append(TVChannelPublicRead.model_validate(channel))
                if cap is not None and len(channels) >= cap:
                    break
            payload.channels = channels
            public.append(payload)
            continue

        if section.type == "series":
            series_items: list[SeriesListItemRead] = []
            for item in rows:
                series = series_by_id.get(item.ref_id)
                if not series:
                    continue
                series_items.append(SeriesListItemRead.model_validate(series))
                if cap is not None and len(series_items) >= cap:
                    break
            payload.series = series_items
            public.append(payload)
            continue

        # movie-bearing rails (and custom may mix — movies first then series in kind order)
        movie_items: list[ContentListItemRead] = []
        mixed_series: list[SeriesListItemRead] = []
        for item in rows:
            if item.item_kind == "movie":
                movie = movies_by_id.get(item.ref_id)
                if not movie:
                    continue
                movie_items.append(ContentListItemRead.model_validate(movie))
            elif item.item_kind == "series":
                series = series_by_id.get(item.ref_id)
                if not series:
                    continue
                mixed_series.append(SeriesListItemRead.model_validate(series))
            total = len(movie_items) + len(mixed_series)
            if cap is not None and total >= cap:
                break
        payload.movies = movie_items
        payload.series = mixed_series
        public.append(payload)

    return public
