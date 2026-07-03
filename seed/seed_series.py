"""
Seed 15 series into the series table (idempotent).

    python seed_series.py

Safe to run in Docker:

    docker compose exec api python seed_series.py
"""

import asyncio
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.series import Series

_POSTER  = "/sample_images/poster.png"
_BANNER  = "/sample_images/banner2.png"
_TRAILER = "https://www.youtube.com/watch?v=98zHKN-xSHk"

SEED_SERIES: list[dict] = [
    {
        "slug": "echo-valley",
        "title": "Echo Valley",
        "description": "A disgraced detective relocates to a quiet valley town where every resident seems to be hiding the same secret — and none of them are willing to talk.",
        "genres": ["Crime", "Mystery", "Drama"],
        "release_year": 2022,
        "rating": Decimal("8.4"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("4.99"),
        "is_published": True,
    },
    {
        "slug": "midnight-run-series",
        "title": "Midnight Run",
        "description": "Three couriers working the overnight shift stumble into an underground courier network that moves things no government wants traced.",
        "genres": ["Thriller", "Action"],
        "release_year": 2023,
        "rating": Decimal("8.1"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("4.99"),
        "is_published": True,
    },
    {
        "slug": "crown-of-thorns",
        "title": "Crown of Thorns",
        "description": "Set in a fictional Southeast Asian kingdom, a prince and a rebel leader fight over the future of a country both claim to love.",
        "genres": ["Drama", "History", "Romance"],
        "release_year": 2021,
        "rating": Decimal("8.7"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("5.99"),
        "is_published": True,
    },
    {
        "slug": "glass-house",
        "title": "Glasshouse",
        "description": "Six strangers enter a fully transparent smart house for a reality competition — but the show's producers know far more about them than they let on.",
        "genres": ["Thriller", "Sci-Fi"],
        "release_year": 2023,
        "rating": Decimal("7.9"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("4.99"),
        "is_published": True,
    },
    {
        "slug": "hollow-coast",
        "title": "Hollow Coast",
        "description": "A marine biologist investigating mass coral death along the Cambodian coast uncovers industrial dumping — and the people willing to kill to hide it.",
        "genres": ["Drama", "Thriller"],
        "release_year": 2022,
        "rating": Decimal("8.0"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("4.99"),
        "is_published": True,
    },
    {
        "slug": "lotus-blood",
        "title": "Lotus Blood",
        "description": "A matriarch's death tears apart a wealthy Phnom Penh family when each sibling receives a different version of her final will.",
        "genres": ["Drama", "Mystery"],
        "release_year": 2023,
        "rating": Decimal("8.5"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("5.99"),
        "is_published": True,
    },
    {
        "slug": "after-hours-series",
        "title": "After Hours",
        "description": "The staff of a high-end Phnom Penh hotel navigate ambition, love, and blackmail — all while keeping their five-star smiles intact.",
        "genres": ["Comedy", "Drama", "Romance"],
        "release_year": 2022,
        "rating": Decimal("7.8"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("3.99"),
        "is_published": True,
    },
    {
        "slug": "final-frame",
        "title": "Final Frame",
        "description": "A photojournalist and a police sketch artist team up after realising their separate cases point to the same man — who died six years ago.",
        "genres": ["Crime", "Mystery"],
        "release_year": 2024,
        "rating": Decimal("8.3"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("4.99"),
        "is_published": True,
    },
    {
        "slug": "red-monsoon",
        "title": "Red Monsoon",
        "description": "In 1970s Cambodia, a young nurse smuggles medicine through conflict zones and falls in love with the enemy she was warned never to trust.",
        "genres": ["Drama", "History", "Romance"],
        "release_year": 2021,
        "rating": Decimal("9.0"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("5.99"),
        "is_published": True,
    },
    {
        "slug": "double-agent",
        "title": "Double Agent",
        "description": "A spy who has been feeding information to both sides for a decade must choose a side when the two agencies finally discover each other.",
        "genres": ["Action", "Thriller", "Sci-Fi"],
        "release_year": 2024,
        "rating": Decimal("8.6"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("5.99"),
        "is_published": True,
    },
    {
        "slug": "the-restaurant",
        "title": "The Restaurant",
        "description": "A Michelin-starred chef leaves Paris to open a street food stall in Siem Reap — and learns that the best cooking has nothing to do with stars.",
        "genres": ["Drama", "Comedy"],
        "release_year": 2023,
        "rating": Decimal("7.7"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("3.99"),
        "is_published": True,
    },
    {
        "slug": "iron-dynasty",
        "title": "Iron Dynasty",
        "description": "When the heir to an industrial empire disappears the night before his coronation, his twin sister must impersonate him to keep the company from collapsing.",
        "genres": ["Action", "Drama", "Thriller"],
        "release_year": 2023,
        "rating": Decimal("8.2"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("4.99"),
        "is_published": True,
    },
    {
        "slug": "the-healer",
        "title": "The Healer",
        "description": "A traditional medicine practitioner and a modern oncologist clash — and fall — while treating the same terminally ill patient in a rural hospital.",
        "genres": ["Drama", "Romance"],
        "release_year": 2022,
        "rating": Decimal("7.6"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("3.99"),
        "is_published": True,
    },
    {
        "slug": "kingdom-of-shadows",
        "title": "Kingdom of Shadows",
        "description": "A secret society that has protected the Angkor temples for centuries faces its greatest threat: a tech billionaire who wants to digitise and sell them.",
        "genres": ["Action", "Adventure", "Mystery"],
        "release_year": 2024,
        "rating": Decimal("8.8"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("5.99"),
        "is_published": True,
    },
    {
        "slug": "neon-nights",
        "title": "Neon Nights",
        "description": "Four friends running an underground music venue in Phnom Penh juggle fame, debt, and each other across three chaotic, unforgettable years.",
        "genres": ["Drama", "Music", "Romance"],
        "release_year": 2023,
        "rating": Decimal("8.1"),
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "monthly_price_usd": Decimal("4.99"),
        "is_published": True,
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
        count = await db.scalar(select(func.count()).select_from(Series))

        if count and count >= 10:
            # Patch missing fields on existing series
            r1 = await db.execute(
                update(Series).where(Series.trailer_url.is_(None)).values(trailer_url=_TRAILER)
            )
            r2 = await db.execute(
                update(Series).where(Series.poster_key.is_(None)).values(poster_key=_POSTER)
            )
            r3 = await db.execute(
                update(Series).where(Series.banner_key.is_(None)).values(banner_key=_BANNER)
            )
            await db.commit()
            print(
                f"Series already exist ({count}). Patched: "
                f"trailer_url={r1.rowcount}, poster_key={r2.rowcount}, banner_key={r3.rowcount}."
            )
            await engine.dispose()
            return

        added = 0
        for row in SEED_SERIES:
            existing = await db.scalar(select(Series).where(Series.slug == row["slug"]))
            if existing:
                print(f"  skip (exists): {row['slug']}")
                continue
            db.add(Series(**row))
            added += 1

        await db.commit()
        print(f"Seeded {added} series.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
