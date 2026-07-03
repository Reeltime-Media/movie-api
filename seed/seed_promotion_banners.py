"""
Seed professional home promotion banners (idempotent).

    python seed_promotion_banners.py

Skips seeding when any banner already exists. Safe to run in Docker:

    docker compose exec api python seed_promotion_banners.py
"""

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.promotion_banner import PromotionBanner

# Unsplash URLs — same cinematic set as the client marketing pages.
THEATER_SEATS = (
    "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba"
    "?auto=format&fit=crop&w=1920&q=80"
)
CINEMA_CURTAINS = (
    "https://images.unsplash.com/photo-1536440136628-849c177e76a1"
    "?auto=format&fit=crop&w=1920&q=80"
)
FILM_PROJECTOR = (
    "https://images.unsplash.com/photo-1478720568477-152d9b164e26"
    "?auto=format&fit=crop&w=1920&q=80"
)

SEED_BANNERS: list[dict] = [
    {
        "title": "Unlock Reeltime Plus",
        "subtitle": (
            "Stream premium series, early premieres, and ad-free watching — "
            "one plan for the whole catalog."
        ),
        "image_key": CINEMA_CURTAINS,
        "cta_label": "View plans",
        "cta_href": "/pricing",
        "placement": "home",
        "is_active": True,
        "sort_order": 0,
    },
    {
        "title": "Cambodian stories, full screen",
        "subtitle": (
            "Khmer cinema, regional favorites, and staff picks — "
            "curated for your next movie night."
        ),
        "image_key": THEATER_SEATS,
        "cta_label": "Browse movies",
        "cta_href": "/movies",
        "placement": "home",
        "is_active": True,
        "sort_order": 1,
    },
    {
        "title": "Complete seasons. Your schedule.",
        "subtitle": (
            "Binge full series with a subscription, or jump in with free episodes "
            "— new drops every week."
        ),
        "image_key": FILM_PROJECTOR,
        "cta_label": "Explore series",
        "cta_href": "/series",
        "placement": "home",
        "is_active": True,
        "sort_order": 2,
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
        count = await db.scalar(select(func.count()).select_from(PromotionBanner))
        if count and count > 0:
            print(f"Promotion banners already exist ({count}) — skipping seed.")
            await engine.dispose()
            return

        for row in SEED_BANNERS:
            db.add(PromotionBanner(**row))

        await db.commit()
        print(f"Seeded {len(SEED_BANNERS)} promotion banners.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
