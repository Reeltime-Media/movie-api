"""Public catalog listing / related / movie detail (read path)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.columns import content_list_load_options, series_list_load_options
from app.catalog.coming_soon import is_coming_soon
from app.catalog.free_today import is_free_today
from app.catalog.related import related_movies, related_series
from app.catalog.search import apply_catalog_genre, apply_catalog_search
from app.catalog.series import free_episode_counts_by_series, get_series_or_404
from app.core.exceptions import NotFoundError
from app.models.content import Content
from app.models.series import Series
from app.models.user import User
from app.schemas.content import ContentListItemRead, ContentRead
from app.schemas.pagination import build_paginated_response
from app.schemas.series import SeriesListItemRead
from app.services.content_access import can_access_content
from app.services.pagination import paginate_query
from app.services.response_cache import CATALOG_TTL_SECONDS, cache_get_async, cache_set_async


async def list_published_series(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    genre: str | None = None,
    free: bool | None = None,
    short: bool | None = None,
):
    cache_key = (
        f"series:search={search}:genre={genre}:free={free}:short={short}:"
        f"page={page}:page_size={page_size}"
    )
    cached = await cache_get_async(cache_key)
    if cached is not None:
        return cached

    stmt = (
        select(Series)
        .options(series_list_load_options())
        .where(Series.is_published.is_(True))
        .order_by(Series.created_at.desc())
    )
    stmt = apply_catalog_search(stmt, Series, search=search)
    stmt = apply_catalog_genre(stmt, Series, genre=genre)
    if short is not None:
        stmt = stmt.where(Series.is_short_movie.is_(short))
    if free:
        has_free_episode = (
            select(Content.id)
            .where(
                Content.series_id == Series.id,
                Content.is_free.is_(True),
                Content.is_published.is_(True),
            )
            .exists()
        )
        stmt = stmt.where(has_free_episode)
    items, total = await paginate_query(db, stmt, page=page, page_size=page_size)
    counts = await free_episode_counts_by_series(db, [item.id for item in items])
    response = build_paginated_response(
        [
            SeriesListItemRead.model_validate(item).model_copy(
                update={"free_episode_count": counts.get(item.id, 0)}
            )
            for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
    await cache_set_async(cache_key, response, ttl_seconds=CATALOG_TTL_SECONDS)
    return response


async def list_related_series(
    db: AsyncSession,
    *,
    slug: str,
    limit: int = 8,
) -> list[SeriesListItemRead]:
    series = await get_series_or_404(db, slug, published_only=True)
    items = await related_series(db, series=series, limit=limit)
    counts = await free_episode_counts_by_series(db, [item.id for item in items])
    return [
        SeriesListItemRead.model_validate(item).model_copy(
            update={"free_episode_count": counts.get(item.id, 0)}
        )
        for item in items
    ]


async def get_series_detail(
    db: AsyncSession,
    *,
    slug: str,
    current_user: User | None,
) -> Series:
    published_only = not current_user or current_user.role != "admin"
    return await get_series_or_404(db, slug, published_only=published_only)


async def list_published_movies(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    genre: str | None = None,
    free: bool | None = None,
):
    cache_key = (
        f"movies:search={search}:genre={genre}:free={free}:"
        f"page={page}:page_size={page_size}"
    )
    cached = await cache_get_async(cache_key)
    if cached is not None:
        return cached

    stmt = (
        select(Content)
        .options(content_list_load_options())
        .where(Content.type == "single", Content.is_published.is_(True))
        .order_by(Content.created_at.desc())
    )
    stmt = apply_catalog_search(stmt, Content, search=search)
    stmt = apply_catalog_genre(stmt, Content, genre=genre)
    if free:
        stmt = stmt.where(Content.is_free.is_(True))
    items, total = await paginate_query(db, stmt, page=page, page_size=page_size)
    response = build_paginated_response(
        [ContentListItemRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    await cache_set_async(cache_key, response, ttl_seconds=CATALOG_TTL_SECONDS)
    return response


async def list_related_movies(
    db: AsyncSession,
    *,
    slug: str,
    limit: int = 8,
) -> list[ContentListItemRead]:
    stmt = select(Content).where(
        Content.slug == slug,
        Content.type == "single",
        Content.is_published.is_(True),
    )
    result = await db.execute(stmt)
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")
    items = await related_movies(db, movie=movie, limit=limit)
    return [ContentListItemRead.model_validate(item) for item in items]


async def get_movie_detail(
    db: AsyncSession,
    *,
    slug: str,
    current_user: User | None,
    guest_id: str | None,
) -> ContentRead:
    stmt = select(Content).where(Content.slug == slug, Content.type == "single")
    result = await db.execute(stmt)
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")

    is_admin = bool(current_user and current_user.role == "admin")
    if not movie.is_published and not is_admin:
        if not await is_coming_soon(db, movie.id):
            raise NotFoundError("Movie not found")

    data = ContentRead.model_validate(movie)
    data.is_free_today = await is_free_today(db, movie.id)
    if not await can_access_content(
        db, current_user, guest_id, movie, is_free_today=data.is_free_today
    ):
        data.hls_master_key = None
    return data
