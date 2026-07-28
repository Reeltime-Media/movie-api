"""
Assign a random rating (6.0-9.0) to any content or series row that doesn't
have one yet (idempotent — only touches rows where rating IS NULL).

    python seed_random_ratings.py

Safe to run in Docker:

    docker compose exec api python seed_random_ratings.py
"""

import asyncio
import random
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.content import Content
from app.models.series import Series

RATING_MIN = 6.0
RATING_MAX = 9.0


def _random_rating() -> Decimal:
    return Decimal(str(round(random.uniform(RATING_MIN, RATING_MAX), 1)))


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        content_rows = (
            await db.scalars(select(Content).where(Content.rating.is_(None)))
        ).all()
        for row in content_rows:
            row.rating = _random_rating()

        series_rows = (
            await db.scalars(select(Series).where(Series.rating.is_(None)))
        ).all()
        for row in series_rows:
            row.rating = _random_rating()

        await db.commit()
        print(
            f"Rated {len(content_rows)} content row(s) and "
            f"{len(series_rows)} series row(s)."
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
