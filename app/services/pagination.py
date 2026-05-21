from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def paginate_query(
    db: AsyncSession,
    stmt: Select,
    *,
    page: int,
    page_size: int,
    scalar: bool = True,
) -> tuple[list, int]:
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = await db.scalar(count_stmt) or 0
    result = await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    if scalar:
        return list(result.scalars().all()), total
    return list(result.all()), total
