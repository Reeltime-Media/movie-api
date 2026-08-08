"""
Seed live TV channels (idempotent).

    python -m seed.seed_tv_channels

Safe to run in Docker:

    docker compose exec api python -m seed.seed_tv_channels

Skips any channel whose slug already exists. Re-running is safe. Channels
are created published and offline — hit the admin "start" endpoint to
actually begin the restream.
"""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.tv_channel import TVChannel
from app.services.content_slug import slugify

SEED_CHANNELS: list[dict] = [
    {
        "slug": "ctv9-hd",
        "name": "CTV9 HD",
        "description": "CTV9 HD live channel.",
        "source_url": "http://36.37.129.119:8083/CTV9HD_BKU2.m3u8",
        "is_free": True,
        "is_published": True,
        "sort_order": 0,
    },
]


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        added = 0
        for row in SEED_CHANNELS:
            slug = slugify(row["slug"])
            existing = await db.scalar(select(TVChannel).where(TVChannel.slug == slug))
            if existing:
                print(f"  skip (exists): {slug}")
                continue
            db.add(
                TVChannel(
                    id=uuid.uuid4(),
                    slug=slug,
                    name=row["name"],
                    description=row.get("description"),
                    source_url=row["source_url"],
                    is_free=row.get("is_free", False),
                    is_published=row.get("is_published", False),
                    sort_order=row.get("sort_order", 0),
                    status="offline",
                )
            )
            added += 1
            print(f"  added: {slug} — {row['name']}")

        await db.commit()
        print(f"\nDone. Seeded {added} channel(s).")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
