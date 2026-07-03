from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
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
