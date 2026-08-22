"""
Seed unpublished Coming Soon movies from public web metadata (idempotent).

Downloads posters from the public source URLs, uploads them to Cloudflare R2
under movies/{slug}/poster.*, optimizes to WebP (+ rail thumb), then creates
draft Content rows and coming_soon_items.

    cd movie-api
    PYTHONPATH=. python seed/seed_coming_soon.py

Or:

    docker compose exec api python seed/seed_coming_soon.py
"""

from __future__ import annotations

import asyncio
import mimetypes
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.coming_soon_item import ComingSoonItem
from app.models.content import Content
from app.schemas.coming_soon import COMING_SOON_MAX
from app.services import r2_keys, storage
from app.services.image_process import optimize_r2_image

# Real upcoming titles + Wikipedia poster sources + YouTube trailers.
SEED_COMING_SOON: list[dict] = [
    {
        "slug": "insidious-out-of-the-further-2026",
        "title": "Insidious: Out of the Further",
        "description": (
            "A young mother discovers she can travel into The Further — and bring "
            "what lives there back to the living world. The Insidious franchise returns."
        ),
        "genres": ["Horror", "Thriller"],
        "release_year": 2026,
        "runtime": "1h 46m",
        "poster_source_url": (
            "https://upload.wikimedia.org/wikipedia/en/5/5c/"
            "Insidious-out-of-the-further-poster.png"
        ),
        "trailer_url": "https://www.youtube.com/watch?v=jxU8FU3o75A",
        "price_usd": Decimal("0.50"),
    },
    {
        "slug": "mutiny-2026",
        "title": "Mutiny",
        "description": (
            "Jason Statham leads a high-seas action thriller directed by "
            "Jean-François Richet, with Annabelle Wallis and Adrian Lester."
        ),
        "genres": ["Action", "Thriller"],
        "release_year": 2026,
        "runtime": None,
        "poster_source_url": (
            "https://upload.wikimedia.org/wikipedia/en/d/d3/Mutiny_poster.jpeg"
        ),
        "trailer_url": "https://www.youtube.com/watch?v=FKSdXH89jbo",
        "price_usd": Decimal("0.50"),
    },
    {
        "slug": "clayface-2026",
        "title": "Clayface",
        "description": (
            "A rising Hollywood star is disfigured and turns to a scientist who "
            "transforms his body into clay — DC's body-horror take on Clayface."
        ),
        "genres": ["Horror", "Thriller"],
        "release_year": 2026,
        "runtime": None,
        "poster_source_url": (
            "https://upload.wikimedia.org/wikipedia/en/4/4f/"
            "Clayface_%28film%29_poster.jpg"
        ),
        "trailer_url": "https://www.youtube.com/watch?v=OGO4Mqvo3jI",
        "price_usd": Decimal("0.50"),
    },
    {
        "slug": "street-fighter-2026",
        "title": "Street Fighter",
        "description": (
            "Chun-Li recruits Ryu and Ken for a martial-arts tournament that puts "
            "them on a collision course with M. Bison in Capcom's latest live-action film."
        ),
        "genres": ["Action", "Comedy"],
        "release_year": 2026,
        "runtime": None,
        "poster_source_url": (
            "https://upload.wikimedia.org/wikipedia/en/d/d4/"
            "Street_Fighter_2026_film_poster.jpeg"
        ),
        "trailer_url": "https://www.youtube.com/watch?v=Xt4X4FvXk2A",
        "price_usd": Decimal("0.50"),
    },
    {
        "slug": "the-dog-stars-2026",
        "title": "The Dog Stars",
        "description": (
            "Ridley Scott adapts Peter Heller's post-apocalyptic novel, starring "
            "Jacob Elordi, Josh Brolin, Margaret Qualley, and Guy Pearce."
        ),
        "genres": ["Sci-Fi", "Drama"],
        "release_year": 2026,
        "runtime": None,
        "poster_source_url": (
            "https://upload.wikimedia.org/wikipedia/en/6/68/"
            "The_Dog_Stars_%28film%29_poster.jpg"
        ),
        "trailer_url": "https://www.youtube.com/watch?v=cmzVY1goqwQ",
        "price_usd": Decimal("0.50"),
    },
    {
        "slug": "practical-magic-2-2026",
        "title": "Practical Magic 2",
        "description": (
            "Sandra Bullock and Nicole Kidman return as the Owens sisters in this "
            "romantic fantasy sequel, scheduled for September 11, 2026."
        ),
        "genres": ["Fantasy", "Romance"],
        "release_year": 2026,
        "runtime": None,
        "poster_source_url": (
            "https://upload.wikimedia.org/wikipedia/en/4/47/"
            "Practical_Magic_2_%28film_poster%29.png"
        ),
        "trailer_url": "https://www.youtube.com/watch?v=Ho10_4IX1jE",
        "price_usd": Decimal("0.50"),
    },
    {
        "slug": "lee-cronins-the-mummy-2026",
        "title": "Lee Cronin's The Mummy",
        "description": (
            "A family is reunited with their long-missing, partially mummified daughter "
            "— and slowly realizes she is possessed. Blumhouse / Atomic Monster horror."
        ),
        "genres": ["Horror"],
        "release_year": 2026,
        "runtime": None,
        "poster_source_url": (
            "https://upload.wikimedia.org/wikipedia/en/d/dc/"
            "Lee_Cronin%27s_The_Mummy.jpg"
        ),
        "trailer_url": "https://www.youtube.com/watch?v=XJ0uv-phsDk",
        "price_usd": Decimal("0.50"),
    },
]


def _guess_content_type(url: str, header_type: str | None) -> str:
    if header_type:
        ctype = header_type.split(";")[0].strip().lower()
        if ctype.startswith("image/"):
            return "image/jpeg" if ctype in {"image/jpg", "image/pjpeg"} else ctype
    guessed, _ = mimetypes.guess_type(url.split("?")[0])
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/jpeg"


def _download_poster(url: str) -> tuple[bytes, str]:
    req = Request(
        url,
        headers={
            "User-Agent": "ReeltimeComingSoonSeed/1.0 (poster ingest; contact=ops@reeltime.fun)",
            "Accept": "image/*,*/*;q=0.8",
        },
    )
    with urlopen(req, timeout=60) as resp:
        data = resp.read()
        ctype = _guess_content_type(url, resp.headers.get("Content-Type"))
    if not data:
        raise RuntimeError(f"empty poster download: {url}")
    return data, ctype


def _is_external_poster(key: str | None) -> bool:
    if not key:
        return True
    return key.startswith("http://") or key.startswith("https://")


async def upload_poster_to_r2(slug: str, source_url: str) -> str:
    """Download source poster → R2 movies/{slug}/poster.* → optimize to webp."""
    try:
        data, content_type = await asyncio.to_thread(_download_poster, source_url)
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        raise RuntimeError(f"download failed for {slug}: {exc}") from exc

    raw_key = r2_keys.movie_poster_key(slug, content_type)

    def _put() -> None:
        storage.put_object_bytes(raw_key, data, content_type)

    await asyncio.to_thread(_put)
    optimized = await optimize_r2_image(raw_key, kind="poster")
    return optimized or raw_key


async def ensure_r2_poster(movie: Content, source_url: str) -> str | None:
    """Upload to R2 when poster is missing or still an external URL."""
    if movie.poster_key and not _is_external_poster(movie.poster_key):
        # Already on R2 — still refresh if object is missing.
        exists = await asyncio.to_thread(storage.object_exists, movie.poster_key)
        if exists:
            return movie.poster_key

    if not source_url:
        return movie.poster_key

    key = await upload_poster_to_r2(movie.slug, source_url)
    movie.poster_key = key
    print(f"  ↑ r2 poster: {key}")
    return key


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        exists = await db.scalar(text("SELECT to_regclass('public.coming_soon_items')"))
        if not exists:
            print("coming_soon_items table missing — run: alembic upgrade head")
            await engine.dispose()
            return

        rail_count = await db.scalar(select(func.count()).select_from(ComingSoonItem)) or 0
        slots_left = max(0, COMING_SOON_MAX - int(rail_count))

        added_movies = 0
        added_rail = 0
        uploaded = 0
        sort_base = await db.scalar(
            select(func.coalesce(func.max(ComingSoonItem.sort_order), -1))
        )
        next_sort = int(sort_base or -1) + 1

        for row in SEED_COMING_SOON:
            source_url = row["poster_source_url"]
            existing = await db.scalar(select(Content).where(Content.slug == row["slug"]))
            if existing:
                movie = existing
                changed = False
                if not movie.trailer_url and row["trailer_url"]:
                    movie.trailer_url = row["trailer_url"]
                    changed = True
                before = movie.poster_key
                try:
                    await ensure_r2_poster(movie, source_url)
                except RuntimeError as exc:
                    print(f"  ! poster upload failed ({row['slug']}): {exc}")
                if movie.poster_key != before:
                    uploaded += 1
                    changed = True
                if changed:
                    await db.flush()
                print(f"  movie exists: {row['slug']}")
            else:
                movie = Content(
                    type="single",
                    slug=row["slug"],
                    title=row["title"],
                    description=row["description"],
                    genres=row["genres"],
                    release_year=row["release_year"],
                    runtime=row["runtime"],
                    poster_key=None,
                    banner_key=None,
                    trailer_url=row["trailer_url"],
                    price_usd=row["price_usd"],
                    status="draft",
                    is_published=False,
                    is_free=False,
                    transcode_status="pending",
                )
                db.add(movie)
                await db.flush()
                try:
                    await ensure_r2_poster(movie, source_url)
                    uploaded += 1
                except RuntimeError as exc:
                    print(f"  ! poster upload failed ({row['slug']}): {exc}")
                await db.flush()
                added_movies += 1
                print(f"  + movie: {row['title']}")

            already = await db.scalar(
                select(ComingSoonItem.id).where(ComingSoonItem.content_id == movie.id)
            )
            if already:
                print(f"  rail exists: {row['slug']}")
                continue
            if slots_left <= 0:
                print(f"  rail full — skip: {row['slug']}")
                continue
            if not movie.poster_key:
                print(f"  no poster — skip rail: {row['slug']}")
                continue

            db.add(
                ComingSoonItem(
                    content_id=movie.id,
                    sort_order=next_sort,
                )
            )
            next_sort += 1
            slots_left -= 1
            added_rail += 1
            print(f"  + coming soon: {row['title']}")

        await db.commit()
        print(
            f"Done. movies={added_movies}, coming_soon={added_rail}, "
            f"r2_posters={uploaded}"
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
