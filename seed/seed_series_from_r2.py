"""
Sync series + episodes from R2 keys into the DB (idempotent).

Seeds only series folders that already exist under series/ in R2 and are
missing (or incomplete) in the database. Does not create fake sample series.

    docker compose exec -e PYTHONPATH=/app api python seed/seed_series_from_r2.py
"""

from __future__ import annotations

import asyncio
import re
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.content import Content
from app.models.series import Series

EPISODE_SLUG_RE = re.compile(r"^(?P<series>.+)-s(?P<season>\d+)e(?P<episode>\d+)$")

# Series present in R2 under series/{slug}/ but not yet fully wired in DB.
SERIES_SEED: list[dict] = [
    {
        "slug": "legend-of-the-white-snake-2006",
        "title": "Legend of the White Snake",
        "description": (
            "Bai Suzhen, a white-snake spirit seeking divinity, falls in love with "
            "the mortal Xu Xian — and must fight fate, prejudice, and a demon-hunting monk."
        ),
        "genres": ["Fantasy", "Romance", "Drama", "Adventure"],
        "release_year": 2006,
        "rating": Decimal("7.8"),
        "poster_key": "series/legend-of-the-white-snake-2006/poster.jpg",
        "banner_key": "series/legend-of-the-white-snake-2006/banner.jpg",
        "monthly_price_usd": Decimal("4.99"),
        "trailer_url": "https://www.youtube.com/watch?v=xIIkYHkLT4s",
        "episodes": 6,
        "hls_ready": True,
    },
    {
        "slug": "the-count-of-gu-2010",
        "title": "The Count of Gu",
        "description": (
            "A period drama of ambition, loyalty, and family power struggles "
            "as rival houses collide across a changing era."
        ),
        "genres": ["Drama", "History", "Romance"],
        "release_year": 2010,
        "rating": Decimal("7.5"),
        "poster_key": "series/the-count-of-gu-2010/poster.webp",
        "banner_key": "series/the-count-of-gu-2010/banner.webp",
        "monthly_price_usd": Decimal("4.99"),
        "trailer_url": "https://www.youtube.com/watch?v=zh0MofJAtr8",
        "episodes": 6,
        "hls_ready": True,
    },
    {
        "slug": "black-white-2009",
        "title": "Black & White",
        "description": (
            "Two mismatched crime solvers are forced to team up in a corrupt city "
            "where police, politicians, and gangs all share the same shadows."
        ),
        "genres": ["Action", "Crime", "Mystery"],
        "release_year": 2009,
        "rating": Decimal("8.0"),
        "poster_key": "series/black-white-2009/poster.jpg",
        "banner_key": "series/black-white-2009/banner.jpg",
        "monthly_price_usd": Decimal("4.99"),
        "trailer_url": "https://www.youtube.com/watch?v=A7s19DL_q5g",
        "episodes": 6,
        # Sources in R2 are broken placeholders; keep rows so catalog is complete.
        "hls_ready": False,
    },
]


def episode_slug(series_slug: str, season: int, episode: int) -> str:
    return f"{series_slug}-s{season:02d}e{episode:02d}"


def episode_hls_key(series_slug: str, ep_slug: str) -> str:
    return f"series/{series_slug}/episodes/{ep_slug}/hls/master.m3u8"


async def upsert_series(db: AsyncSession, spec: dict) -> Series:
    result = await db.execute(select(Series).where(Series.slug == spec["slug"]))
    series = result.scalar_one_or_none()
    if series is None:
        series = Series(
            id=uuid.uuid4(),
            slug=spec["slug"],
            title=spec["title"],
            description=spec["description"],
            genres=list(spec["genres"]),
            release_year=spec["release_year"],
            rating=spec["rating"],
            poster_key=spec["poster_key"],
            banner_key=spec["banner_key"],
            trailer_url=spec.get("trailer_url"),
            monthly_price_usd=spec["monthly_price_usd"],
            is_published=True,
        )
        db.add(series)
        await db.flush()
        print(f"  + series {spec['slug']}")
    else:
        series.title = spec["title"]
        series.description = spec["description"]
        series.genres = list(spec["genres"])
        series.release_year = spec["release_year"]
        series.rating = spec["rating"]
        series.poster_key = spec["poster_key"]
        series.banner_key = spec["banner_key"]
        if spec.get("trailer_url"):
            series.trailer_url = spec["trailer_url"]
        series.monthly_price_usd = spec["monthly_price_usd"]
        series.is_published = True
        print(f"  ~ series {spec['slug']}")
    return series


async def upsert_episodes(db: AsyncSession, series: Series, spec: dict) -> int:
    created = 0
    season = 1
    for ep_num in range(1, int(spec["episodes"]) + 1):
        slug = episode_slug(series.slug, season, ep_num)
        result = await db.execute(
            select(Content).where(Content.slug == slug, Content.type == "episode")
        )
        episode = result.scalar_one_or_none()
        ready = bool(spec["hls_ready"])
        hls_key = episode_hls_key(series.slug, slug) if ready else None
        title = f"Episode {ep_num}"

        if episode is None:
            episode = Content(
                id=uuid.uuid4(),
                type="episode",
                series_id=series.id,
                season_number=season,
                episode_number=ep_num,
                slug=slug,
                title=title,
                description=None,
                genres=list(spec["genres"]),
                release_year=spec["release_year"],
                poster_key=spec["poster_key"],
                banner_key=None,
                hls_master_key=hls_key,
                status="published",
                is_published=True,
                is_free=ep_num <= 2,
                transcode_status="ready" if ready else "failed",
            )
            db.add(episode)
            created += 1
            print(f"    + episode {slug} ({episode.transcode_status})")
        else:
            episode.series_id = series.id
            episode.season_number = season
            episode.episode_number = ep_num
            episode.title = title
            episode.genres = list(spec["genres"])
            episode.release_year = spec["release_year"]
            episode.poster_key = episode.poster_key or spec["poster_key"]
            if ready:
                episode.hls_master_key = hls_key
                episode.transcode_status = "ready"
            elif not episode.hls_master_key:
                episode.transcode_status = "failed"
            episode.status = "published"
            episode.is_published = True
            episode.is_free = ep_num <= 2
            print(f"    ~ episode {slug} ({episode.transcode_status})")
    return created


async def main() -> None:
    async with AsyncSessionLocal() as db:
        print("Seeding series from R2 inventory…")
        total_eps = 0
        for spec in SERIES_SEED:
            series = await upsert_series(db, spec)
            total_eps += await upsert_episodes(db, series, spec)
        await db.commit()

        result = await db.execute(select(Series).order_by(Series.slug))
        series_rows = result.scalars().all()
        print()
        print(f"Done. series in DB: {len(series_rows)}")
        for s in series_rows:
            eps = await db.execute(
                select(Content).where(
                    Content.series_id == s.id, Content.type == "episode"
                )
            )
            ep_list = eps.scalars().all()
            ready = sum(1 for e in ep_list if e.transcode_status == "ready")
            print(
                f"  {s.slug}: published={s.is_published} "
                f"episodes={len(ep_list)} ready={ready} genres={s.genres}"
            )


if __name__ == "__main__":
    asyncio.run(main())
