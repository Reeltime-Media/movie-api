"""
Seed live TV channels (idempotent).

    python -m seed.seed_tv_channels

Safe to run in Docker:

    docker compose exec api python -m seed.seed_tv_channels

Skips any channel whose slug already exists. Re-running is safe. Channels
are created published + free; hit the admin "start" endpoint (or the
`--start` flag) to begin restreaming.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.tv_channel import TVChannel
from app.services import live_client
from app.services.content_slug import slugify

# Free / public demo HLS sources so the TV app has a browsable free lineup.
# Real Cambodia feeds (beyond TV9) return 401 on this origin — swap source_url
# in admin when you get licensed streams.
SEED_CHANNELS: list[dict] = [
    {
        "slug": "tv9",
        "name": "TV9",
        "description": "TV9 HD live channel.",
        "source_url": "http://36.37.129.119:8083/CTV9HD_BKU2.m3u8",
        "is_free": True,
        "is_published": True,
        "sort_order": 0,
    },
    {
        "slug": "free-mix",
        "name": "Free Mix",
        "description": "Public free HLS demo channel.",
        "source_url": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
        "is_free": True,
        "is_published": True,
        "sort_order": 10,
    },
    {
        "slug": "open-cinema",
        "name": "Open Cinema",
        "description": "Public Longtail HLS demo stream.",
        "source_url": "https://playertest.longtailvideo.com/adaptive/wowzaid3/playlist.m3u8",
        "is_free": True,
        "is_published": True,
        "sort_order": 20,
    },
    {
        "slug": "stream-lab",
        "name": "Stream Lab",
        "description": "Mux public HLS demo stream.",
        "source_url": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
        "is_free": True,
        "is_published": True,
        "sort_order": 30,
    },
    {
        "slug": "night-owl",
        "name": "Night Owl",
        "description": "Public Longtail HLS demo stream.",
        "source_url": "https://playertest.longtailvideo.com/adaptive/wowzaid3/playlist.m3u8",
        "is_free": True,
        "is_published": True,
        "sort_order": 40,
    },
    {
        "slug": "plaza-live",
        "name": "Plaza Live",
        "description": "Mux public HLS demo stream.",
        "source_url": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
        "is_free": True,
        "is_published": True,
        "sort_order": 50,
    },
]


async def seed(*, start: bool) -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    created: list[TVChannel] = []
    async with session_factory() as db:
        added = 0
        for row in SEED_CHANNELS:
            slug = slugify(row["slug"])
            existing = await db.scalar(select(TVChannel).where(TVChannel.slug == slug))
            if existing:
                # Keep lineup public/free without clobbering a custom source.
                changed = False
                if not existing.is_free:
                    existing.is_free = True
                    changed = True
                if not existing.is_published:
                    existing.is_published = True
                    changed = True
                print(f"  skip (exists): {slug}" + (" [opened free+published]" if changed else ""))
                created.append(existing)
                continue
            channel = TVChannel(
                id=uuid.uuid4(),
                slug=slug,
                name=row["name"],
                description=row.get("description"),
                source_url=row["source_url"],
                is_free=row.get("is_free", True),
                is_published=row.get("is_published", True),
                sort_order=row.get("sort_order", 0),
                status="offline",
            )
            db.add(channel)
            created.append(channel)
            added += 1
            print(f"  added: {slug} — {row['name']}")

        await db.commit()
        for channel in created:
            await db.refresh(channel)
        print(f"\nDone. Seeded {added} new channel(s).")

        if start:
            print("\nStarting restreams…")
            for channel in created:
                try:
                    result = await live_client.start_channel(
                        str(channel.id), channel.source_url
                    )
                    channel.status = result.get("status") or "starting"
                    channel.hls_playback_url = result.get("hls_url")
                    channel.status_error = None
                    print(f"  start {channel.slug}: {channel.status}")
                except Exception as exc:  # noqa: BLE001 — seed must keep going
                    channel.status = "error"
                    channel.status_error = str(exc)[:500]
                    print(f"  start {channel.slug}: ERROR {exc}")
            await db.commit()

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start",
        action="store_true",
        help="Also call the live restream service to put channels on air.",
    )
    args = parser.parse_args()
    asyncio.run(seed(start=args.start))
