"""
Seed 20 movies into the content table (idempotent).

    python seed_movies.py

Skips seeding when 10 or more single-type content rows already exist.
Safe to run in Docker:

    docker compose exec api python seed_movies.py
"""

import asyncio

from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.content import Content

_POSTER = "/sample_images/poster.png"
_BANNER = "/sample_images/banner2.png"
_TRAILER = "https://www.youtube.com/watch?v=98zHKN-xSHk"

SEED_MOVIES: list[dict] = [
    {
        "type": "single",
        "slug": "the-last-drive",
        "title": "The Last Drive",
        "description": "A rideshare driver picks up the wrong passenger on a quiet Tuesday. By dawn, half the city is hunting them, and the truth is more dangerous than either of them.",
        "genres": ["Action", "Thriller"],
        "release_year": 2023,
        "rating": Decimal("8.7"),
        "runtime": "2h 14m",
        "duration_seconds": 8040,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("2.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "angkor-rising",
        "title": "Angkor Rising",
        "description": "Deep in the Cambodian jungle, a young archaeologist uncovers ruins that were never meant to be found — and the secret that buried them.",
        "genres": ["Drama", "Adventure"],
        "release_year": 2022,
        "rating": Decimal("7.9"),
        "runtime": "1h 58m",
        "duration_seconds": 7080,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("0.00"),
        "status": "published",
        "is_published": True,
        "is_free": True,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "neon-city",
        "title": "Neon City",
        "description": "A disgraced detective returns to the city that broke him, chasing a ghost who turns out to be very much alive.",
        "genres": ["Crime", "Thriller"],
        "release_year": 2023,
        "rating": Decimal("8.2"),
        "runtime": "2h 02m",
        "duration_seconds": 7320,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("3.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "the-silent-mountain",
        "title": "The Silent Mountain",
        "description": "Two estranged brothers reunite to sell their childhood home and discover their father left behind far more than just the house.",
        "genres": ["Drama"],
        "release_year": 2021,
        "rating": Decimal("7.5"),
        "runtime": "1h 44m",
        "duration_seconds": 6240,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("0.00"),
        "status": "published",
        "is_published": True,
        "is_free": True,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "iron-fist-rising",
        "title": "Iron Fist Rising",
        "description": "When a small village militia takes on the largest cartel in Southeast Asia, they have one advantage: nothing left to lose.",
        "genres": ["Action"],
        "release_year": 2024,
        "rating": Decimal("8.4"),
        "runtime": "1h 52m",
        "duration_seconds": 6720,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("2.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "midnight-crossing",
        "title": "Midnight Crossing",
        "description": "A border patrol officer discovers a smuggling network that reaches all the way back to her own precinct.",
        "genres": ["Thriller", "Crime"],
        "release_year": 2022,
        "rating": Decimal("7.8"),
        "runtime": "1h 49m",
        "duration_seconds": 6540,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("1.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "shadow-of-the-lotus",
        "title": "Shadow of the Lotus",
        "description": "An undercover agent falls in love with the woman she was sent to investigate, with lives on both sides hanging in the balance.",
        "genres": ["Action", "Drama"],
        "release_year": 2023,
        "rating": Decimal("8.1"),
        "runtime": "2h 08m",
        "duration_seconds": 7680,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("3.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "the-forgotten-temple",
        "title": "The Forgotten Temple",
        "description": "A film crew documenting an abandoned temple begins to vanish one by one, leaving only their footage behind.",
        "genres": ["Horror"],
        "release_year": 2022,
        "rating": Decimal("7.3"),
        "runtime": "1h 38m",
        "duration_seconds": 5880,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("2.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "city-of-dreams",
        "title": "City of Dreams",
        "description": "Three strangers arrive in Phnom Penh on the same day, each chasing a different version of the same dream.",
        "genres": ["Drama", "Romance"],
        "release_year": 2021,
        "rating": Decimal("7.6"),
        "runtime": "1h 55m",
        "duration_seconds": 6900,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("0.00"),
        "status": "published",
        "is_published": True,
        "is_free": True,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "bullet-storm",
        "title": "Bullet Storm",
        "description": "A retired hitman comes out of hiding when his daughter is taken as leverage against him by his former employer.",
        "genres": ["Action"],
        "release_year": 2024,
        "rating": Decimal("8.5"),
        "runtime": "1h 46m",
        "duration_seconds": 6360,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("3.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "the-rivers-secret",
        "title": "The River's Secret",
        "description": "Along the Mekong, a fisherman's discovery triggers a cascade of events that rewrites the history of an entire province.",
        "genres": ["Mystery", "Drama"],
        "release_year": 2022,
        "rating": Decimal("7.7"),
        "runtime": "2h 00m",
        "duration_seconds": 7200,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("1.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "the-golden-mask",
        "title": "The Golden Mask",
        "description": "An antique thief takes one final job — stealing a ceremonial mask from a heavily guarded royal exhibition — and nothing goes to plan.",
        "genres": ["Action", "Adventure"],
        "release_year": 2023,
        "rating": Decimal("8.0"),
        "runtime": "1h 58m",
        "duration_seconds": 7080,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("2.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "sleepless-in-phnom-penh",
        "title": "Sleepless in Phnom Penh",
        "description": "A workaholic food critic and a street chef with zero social media presence keep clashing — until they can't stop thinking about each other.",
        "genres": ["Comedy", "Romance"],
        "release_year": 2022,
        "rating": Decimal("7.4"),
        "runtime": "1h 42m",
        "duration_seconds": 6120,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("0.00"),
        "status": "published",
        "is_published": True,
        "is_free": True,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "the-dark-harvest",
        "title": "The Dark Harvest",
        "description": "After a drought ends a decade-long run of perfect crops, the farmers of a remote valley begin to suspect the land is asking for something in return.",
        "genres": ["Horror", "Thriller"],
        "release_year": 2023,
        "rating": Decimal("7.9"),
        "runtime": "1h 51m",
        "duration_seconds": 6660,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("2.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "chronicles-of-the-kingdom",
        "title": "Chronicles of the Kingdom",
        "description": "An epic retelling of the founding of the Khmer empire, seen through the eyes of the general who built it and the king who claimed it.",
        "genres": ["Drama", "History"],
        "release_year": 2021,
        "rating": Decimal("8.3"),
        "runtime": "2h 28m",
        "duration_seconds": 8880,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("1.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "storm-chaser",
        "title": "Storm Chaser",
        "description": "A meteorologist tracking an unprecedented typhoon realises the storm is the least of her problems when a government cover-up surfaces in its path.",
        "genres": ["Action", "Thriller"],
        "release_year": 2024,
        "rating": Decimal("8.6"),
        "runtime": "2h 05m",
        "duration_seconds": 7500,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("3.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "love-in-the-rain",
        "title": "Love in the Rain",
        "description": "During monsoon season, a nurse and a travel photographer are stranded in a countryside guesthouse with nothing to do but talk — and fall.",
        "genres": ["Romance", "Drama"],
        "release_year": 2022,
        "rating": Decimal("7.2"),
        "runtime": "1h 39m",
        "duration_seconds": 5940,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("0.00"),
        "status": "published",
        "is_published": True,
        "is_free": True,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "the-final-guardian",
        "title": "The Final Guardian",
        "description": "The last of an ancient order of protectors must pass on her powers before the next eclipse — to a teenager who wants nothing to do with destiny.",
        "genres": ["Action", "Sci-Fi"],
        "release_year": 2023,
        "rating": Decimal("8.2"),
        "runtime": "2h 11m",
        "duration_seconds": 7860,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("2.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "echoes-of-war",
        "title": "Echoes of War",
        "description": "Based on true events: a journalist returns to the village where she was born during the conflict and discovers her own family's untold role in it.",
        "genres": ["Action", "Drama"],
        "release_year": 2022,
        "rating": Decimal("8.4"),
        "runtime": "2h 18m",
        "duration_seconds": 8280,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("1.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
    },
    {
        "type": "single",
        "slug": "crown-of-ash",
        "title": "Crown of Ash",
        "description": "A warlord's heir must choose between avenging her father or saving the people his wars destroyed — a choice with no clean answer.",
        "genres": ["Action", "Drama"],
        "release_year": 2023,
        "rating": Decimal("8.8"),
        "runtime": "2h 22m",
        "duration_seconds": 8520,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": _TRAILER,
        "price_usd": Decimal("3.99"),
        "status": "published",
        "is_published": True,
        "is_free": False,
        "transcode_status": "pending",
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
        count = await db.scalar(
            select(func.count()).select_from(Content).where(Content.type == "single")
        )
        if count and count >= 10:
            # Movies already exist — patch missing trailer URLs and poster/banner keys
            r1 = await db.execute(
                update(Content)
                .where(Content.type == "single", Content.trailer_url.is_(None))
                .values(trailer_url=_TRAILER)
            )
            r2 = await db.execute(
                update(Content)
                .where(Content.type == "single", Content.poster_key.is_(None))
                .values(poster_key=_POSTER)
            )
            r3 = await db.execute(
                update(Content)
                .where(Content.type == "single", Content.banner_key.is_(None))
                .values(banner_key=_BANNER)
            )
            await db.commit()
            print(
                f"Patched: trailer_url={r1.rowcount}, "
                f"poster_key={r2.rowcount}, "
                f"banner_key={r3.rowcount} movie(s)."
            )
            await engine.dispose()
            return

        added = 0
        for row in SEED_MOVIES:
            existing = await db.scalar(
                select(Content).where(Content.slug == row["slug"])
            )
            if existing:
                print(f"  skip (exists): {row['slug']}")
                continue
            db.add(Content(**row))
            added += 1

        await db.commit()
        print(f"Seeded {added} movies.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
