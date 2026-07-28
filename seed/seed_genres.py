"""
Seed the catalog category genres used by the client nav dropdowns
(Movies / Series menus). Idempotent — existing genres are kept.

    python seed/seed_genres.py
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.genre import Genre

settings = get_settings()

# Keep in sync with movie-client top-nav category dropdowns.
CATEGORY_GENRES = [
    "Action",
    "Hollywood",
    "Horror",
    "Cartoon",
    "Love story",
    "Khmer",
    "Chinese",
    "Korean",
    "India",
    "Japan",
    "Indonesia",
]


async def seed():
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        result = await db.execute(select(Genre.name))
        existing = {name.strip().lower() for name in result.scalars()}

        created = []
        for name in CATEGORY_GENRES:
            if name.lower() in existing:
                continue
            db.add(Genre(name=name))
            created.append(name)

        await db.commit()

        if created:
            print(f"Created {len(created)} genres: {', '.join(created)}")
        else:
            print("All category genres already exist — nothing to do.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
