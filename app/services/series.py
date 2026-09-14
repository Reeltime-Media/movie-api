from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.content import Content
from app.models.series import Series


async def get_series_or_404(
    db: AsyncSession,
    slug: str,
    *,
    published_only: bool = False,
) -> Series:
    stmt = select(Series).where(Series.slug == slug)
    if published_only:
        stmt = stmt.where(Series.is_published.is_(True))
    result = await db.execute(stmt)
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")
    return series


async def free_episode_counts_by_series(
    db: AsyncSession,
    series_ids: list[UUID],
) -> dict[UUID, int]:
    if not series_ids:
        return {}
    stmt = (
        select(Content.series_id, func.count())
        .where(
            Content.series_id.in_(series_ids),
            Content.type == "episode",
            Content.is_free.is_(True),
            Content.is_published.is_(True),
        )
        .group_by(Content.series_id)
    )
    rows = (await db.execute(stmt)).all()
    return {row[0]: int(row[1]) for row in rows if row[0] is not None}
