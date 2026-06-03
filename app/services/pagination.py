import asyncio

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_connect import is_transient_db_error


async def paginate_query(
    db: AsyncSession,
    stmt: Select,
    *,
    page: int,
    page_size: int,
    scalar: bool = True,
) -> tuple[list, int]:
    last_error: BaseException | None = None
    for attempt in range(1, 4):
        try:
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = await db.scalar(count_stmt) or 0
            result = await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
            if scalar:
                return list(result.scalars().all()), total
            return list(result.all()), total
        except BaseException as exc:
            last_error = exc
            await db.rollback()
            if not is_transient_db_error(exc) or attempt >= 3:
                raise
            await asyncio.sleep(0.5 * attempt)
    assert last_error is not None
    raise last_error
