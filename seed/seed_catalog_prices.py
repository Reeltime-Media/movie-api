"""
Overwrite catalog prices to the current Reeltime card (idempotent).

    PYTHONPATH=. python seed/seed_catalog_prices.py

Safe to run in Docker:

    docker compose exec -e PYTHONPATH=/app api python seed/seed_catalog_prices.py

Paid movies (type=single, is_free=false) → $0.50.
Free movies are left unchanged.
Every series monthly_price_usd → $2.50.
"""

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.content import Content
from app.models.series import Series
from seed.pricing_catalog import PAID_MOVIE_PRICE_USD, SERIES_PRICE_USD


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        movies = await db.execute(
            update(Content)
            .where(Content.type == "single", Content.is_free.is_(False))
            .values(price_usd=PAID_MOVIE_PRICE_USD)
        )
        series = await db.execute(
            update(Series).values(monthly_price_usd=SERIES_PRICE_USD)
        )
        await db.commit()
        print(
            f"Updated {movies.rowcount} paid movie(s) to ${PAID_MOVIE_PRICE_USD} "
            f"and {series.rowcount} series to ${SERIES_PRICE_USD}."
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
