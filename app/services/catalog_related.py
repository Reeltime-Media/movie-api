"""Related catalog items ranked by shared genres."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.models.series import Series


async def related_movies(
    db: AsyncSession,
    *,
    movie: Content,
    limit: int = 8,
) -> list[Content]:
    genres = [g for g in (movie.genres or []) if g]
    stmt = (
        select(Content)
        .where(
            Content.type == "single",
            Content.is_published.is_(True),
            Content.id != movie.id,
        )
        .order_by(Content.created_at.desc())
        .limit(limit)
    )
    if genres:
        stmt = (
            select(Content)
            .where(
                Content.type == "single",
                Content.is_published.is_(True),
                Content.id != movie.id,
                Content.genres.overlap(genres),
            )
            .order_by(Content.created_at.desc())
            .limit(limit)
        )

    result = await db.execute(stmt)
    items = list(result.scalars().all())
    if len(items) >= limit or not genres:
        return items

    existing_ids = {movie.id, *(m.id for m in items)}
    fallback = await db.execute(
        select(Content)
        .where(
            Content.type == "single",
            Content.is_published.is_(True),
            Content.id.not_in(existing_ids),
        )
        .order_by(Content.created_at.desc())
        .limit(limit - len(items))
    )
    return items + list(fallback.scalars().all())


async def related_series(
    db: AsyncSession,
    *,
    series: Series,
    limit: int = 8,
) -> list[Series]:
    genres = [g for g in (series.genres or []) if g]
    stmt = (
        select(Series)
        .where(
            Series.is_published.is_(True),
            Series.id != series.id,
        )
        .order_by(Series.created_at.desc())
        .limit(limit)
    )
    if genres:
        stmt = (
            select(Series)
            .where(
                Series.is_published.is_(True),
                Series.id != series.id,
                Series.genres.overlap(genres),
            )
            .order_by(Series.created_at.desc())
            .limit(limit)
        )

    result = await db.execute(stmt)
    items = list(result.scalars().all())
    if len(items) >= limit or not genres:
        return items

    existing_ids = {series.id, *(s.id for s in items)}
    fallback = await db.execute(
        select(Series)
        .where(
            Series.is_published.is_(True),
            Series.id.not_in(existing_ids),
        )
        .order_by(Series.created_at.desc())
        .limit(limit - len(items))
    )
    return items + list(fallback.scalars().all())
