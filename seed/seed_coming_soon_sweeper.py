"""
Seed 5 test movies with status="coming_soon" + release_at (idempotent) — for
exercising the auto-publish sweeper (app/services/coming_soon_sweeper.py).

Distinct from seed_coming_soon.py, which seeds the admin-curated Coming Soon
*rail* (coming_soon_items) with real posters uploaded to R2. This script only
drives the status/release_at state machine; it does not touch the rail.

    cd movie-api
    PYTHONPATH=. python seed/seed_coming_soon_sweeper.py

Or:

    docker compose exec api python seed/seed_coming_soon_sweeper.py

Covers every branch of the coming-soon state machine:

  - no-announcement    : status=coming_soon, release_at=None (TBA), no video.
                         Never auto-promotes — needs a manual "Publish now".
  - announced-future   : release_at ~2 weeks out, no video yet. Not due.
  - announced-uploading: release_at ~6 weeks out, video mid-transcode. Not due.
  - due-and-ready      : release_at ~2 days AGO + a (fake) ready hls_master_key.
                         The coming_soon_sweeper should flip this to
                         'published' within ~60s of the API starting — the
                         core thing to watch to confirm the sweeper works.
  - due-but-no-video   : release_at ~1 day AGO, no video. Proves the sweeper
                         correctly leaves it alone until a video is attached.

The poster/banner keys point at "/sample_images/poster.png" and
"/sample_images/banner2.png" — the same pre-uploaded R2 objects
`seed_movies.py` already uses (mirrored locally at
movie-client/public/sample_images/ for reference). No R2 upload needed.

The "due-and-ready" row's hls_master_key is a made-up key, not a real
transcoded file — it exists only to satisfy the publish-readiness check so
you can observe the sweeper promote it. Its watch page will 404 if you try
to actually play it; replace with a real upload if you need real playback.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.content import Content
from app.services.r2_keys import movie_hls_master_key

_POSTER = "/sample_images/poster.png"
_BANNER = "/sample_images/banner2.png"

_NOW = datetime.now(timezone.utc)


def _hls_ready_key(slug: str) -> str:
    return movie_hls_master_key(slug)


SEED_COMING_SOON: list[dict] = [
    {
        "type": "single",
        "slug": "spider-verse-brand-new-day",
        "title": "Spider-Verse: Brand New Day II",
        "title_km": "មនុស្សអៀនពពក ២",
        "description": "The sequel nobody saw coming — a new chapter in the Brand New Day saga.",
        "genres": ["Action", "Sci-Fi"],
        "release_year": 2026,
        "rating": None,
        "runtime": None,
        "duration_seconds": None,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": None,
        "price_usd": Decimal("4.99"),
        "status": "coming_soon",
        "release_at": None,  # TBA — no announced date
        "is_published": False,
        "is_free": False,
        "transcode_status": "pending",
        "hls_master_key": None,
    },
    {
        "type": "single",
        "slug": "midnight-requiem",
        "title": "Midnight Requiem",
        "description": "A concert pianist inherits a haunted opera house — and a debt only one more performance can settle.",
        "genres": ["Horror", "Drama"],
        "release_year": 2026,
        "rating": None,
        "runtime": None,
        "duration_seconds": None,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": None,
        "price_usd": Decimal("3.99"),
        "status": "coming_soon",
        "release_at": _NOW + timedelta(days=14),
        "is_published": False,
        "is_free": False,
        "transcode_status": "pending",
        "hls_master_key": None,
    },
    {
        "type": "single",
        "slug": "ghosts-of-tonle-sap",
        "title": "Ghosts of Tonle Sap",
        "description": "A fishing village on the great lake confronts a legend that keeps returning — one flood season at a time.",
        "genres": ["Horror", "Mystery"],
        "release_year": 2026,
        "rating": None,
        "runtime": None,
        "duration_seconds": None,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": None,
        "price_usd": Decimal("2.99"),
        "status": "coming_soon",
        "release_at": _NOW + timedelta(days=45),
        "is_published": False,
        "is_free": False,
        "transcode_status": "processing",  # video mid-upload/transcode
        "hls_master_key": None,
    },
    {
        "type": "single",
        "slug": "the-last-ember",
        "title": "The Last Ember",
        "description": "The final keeper of a dying forge must decide whether her craft is worth passing on to a world that has moved on.",
        "genres": ["Drama"],
        "release_year": 2026,
        "rating": Decimal("8.1"),
        "runtime": "1h 56m",
        "duration_seconds": 7020,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": None,
        "price_usd": Decimal("3.99"),
        "status": "coming_soon",
        "release_at": _NOW - timedelta(days=2),  # already due
        "is_published": False,
        "is_free": False,
        "transcode_status": "ready",
        # Fake key — see module docstring. Just needs to be non-null for the
        # sweeper's publish-readiness check to pass.
        "hls_master_key": _hls_ready_key("the-last-ember"),
    },
    {
        "type": "single",
        "slug": "crimson-horizon",
        "title": "Crimson Horizon",
        "description": "When a border skirmish escalates overnight, a field medic and a war photographer are the only ones left to tell what really happened.",
        "genres": ["Action", "Drama"],
        "release_year": 2026,
        "rating": None,
        "runtime": None,
        "duration_seconds": None,
        "poster_key": _POSTER,
        "banner_key": _BANNER,
        "trailer_url": None,
        "price_usd": Decimal("3.99"),
        "status": "coming_soon",
        "release_at": _NOW - timedelta(days=1),  # already due, but no video
        "is_published": False,
        "is_free": False,
        "transcode_status": "pending",
        "hls_master_key": None,
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
        for row in SEED_COMING_SOON:
            existing = await db.scalar(select(Content).where(Content.slug == row["slug"]))
            if existing:
                print(f"  skip (exists): {row['slug']}")
                continue
            db.add(Content(**row))
            added += 1

        await db.commit()
        print(f"Seeded {added} coming-soon movie(s).")
        if added:
            print(
                "Watch 'the-last-ember' — it's already due with a (fake) ready video, "
                "so the coming_soon_sweeper should promote it to 'published' within "
                f"~{max(5, settings.coming_soon_sweeper_interval_seconds)}s of the API running."
            )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
