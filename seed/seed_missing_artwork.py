"""
Fill missing movie posters/banners in R2 + content rows (idempotent).

Looks up Wikipedia infobox posters and YouTube trailer stills, uploads them
to movies/{slug}/poster.* and movies/{slug}/banner.*, then optimizes to WebP.

    cd movie-api
    PYTHONPATH=. python seed/seed_missing_artwork.py
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.content import Content
from app.services import r2_keys, storage
from app.services.image_process import optimize_r2_image

USER_AGENT = "ReeltimeArtworkSeed/1.0 (artwork ingest; contact=ops@reeltime.fun)"

# Wikipedia REST titles for movies that have no real poster in R2.
WIKI_PAGES: dict[str, str] = {
    "hitman-agent-jun-2020": "Hitman:_Agent_Jun",
    "tune-in-for-love-2019": "Tune_in_for_Love",
    "spider-verse-brand-new-day": "Spider-Man:_Brand_New_Day",
}

# Set trailer when missing so we can also pull a landscape banner still.
TRAILER_URLS: dict[str, str] = {
    "spider-verse-brand-new-day": "https://www.youtube.com/watch?v=wpCvXR406N4",
}

_YOUTUBE_ID = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{11})"
)


def _is_missing_key(key: str | None) -> bool:
    if key is None:
        return True
    stripped = key.strip()
    if not stripped:
        return True
    if stripped.startswith("http://") or stripped.startswith("https://"):
        return True
    if "sample_images" in stripped:
        return True
    return False


def _guess_content_type(url: str, header_type: str | None) -> str:
    if header_type:
        ctype = header_type.split(";")[0].strip().lower()
        if ctype.startswith("image/"):
            return "image/jpeg" if ctype in {"image/jpg", "image/pjpeg"} else ctype
    guessed, _ = mimetypes.guess_type(urlparse(url).path)
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/jpeg"


def _download_image(url: str) -> tuple[bytes, str]:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "image/*,*/*;q=0.8",
        },
    )
    with urlopen(req, timeout=60) as resp:
        data = resp.read()
        ctype = _guess_content_type(url, resp.headers.get("Content-Type"))
    if not data:
        raise RuntimeError(f"empty download: {url}")
    return data, ctype


def _youtube_id(url: str | None) -> str | None:
    if not url:
        return None
    match = _YOUTUBE_ID.search(url)
    return match.group(1) if match else None


def _wikipedia_poster_url(wiki_title: str) -> str | None:
    api = f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_title}"
    req = Request(api, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    original = payload.get("originalimage") or payload.get("thumbnail") or {}
    source = original.get("source")
    return source if isinstance(source, str) and source.startswith("http") else None


def _youtube_still_url(video_id: str) -> str | None:
    for name in ("maxresdefault", "sddefault", "hqdefault"):
        url = f"https://i.ytimg.com/vi/{video_id}/{name}.jpg"
        req = Request(
            url,
            method="HEAD",
            headers={"User-Agent": USER_AGENT, "Accept": "image/jpeg"},
        )
        try:
            with urlopen(req, timeout=20) as resp:
                if resp.status == 200:
                    return url
        except (HTTPError, URLError, TimeoutError):
            continue
    return None


async def _upload_kind(slug: str, kind: str, source_url: str) -> str:
    try:
        data, content_type = await asyncio.to_thread(_download_image, source_url)
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        raise RuntimeError(f"{kind} download failed for {slug}: {exc}") from exc

    raw_key = (
        r2_keys.movie_poster_key(slug, content_type)
        if kind == "poster"
        else r2_keys.movie_banner_key(slug, content_type)
    )

    def _put() -> None:
        storage.put_object_bytes(raw_key, data, content_type)

    await asyncio.to_thread(_put)
    image_kind = "poster" if kind == "poster" else "banner"
    optimized = await optimize_r2_image(raw_key, kind=image_kind)
    return optimized or raw_key


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    posters = 0
    banners = 0
    skipped = 0

    async with session_factory() as db:
        movies = (
            await db.scalars(
                select(Content).where(Content.type == "single").order_by(Content.title)
            )
        ).all()

        for movie in movies:
            needs_poster = _is_missing_key(movie.poster_key)
            needs_banner = _is_missing_key(movie.banner_key)
            if not needs_poster and not needs_banner:
                continue

            if not movie.trailer_url and movie.slug in TRAILER_URLS:
                movie.trailer_url = TRAILER_URLS[movie.slug]
                print(f"  trailer: {movie.slug}")

            changed = False
            print(
                f"* {movie.slug}  poster={'need' if needs_poster else 'ok'}  "
                f"banner={'need' if needs_banner else 'ok'}  {movie.title}"
            )

            if needs_poster:
                wiki_title = WIKI_PAGES.get(movie.slug)
                if not wiki_title:
                    print("    skip poster (no Wikipedia mapping)")
                    skipped += 1
                else:
                    try:
                        source = await asyncio.to_thread(
                            _wikipedia_poster_url, wiki_title
                        )
                        if not source:
                            raise RuntimeError("Wikipedia returned no image")
                        movie.poster_key = await _upload_kind(
                            movie.slug, "poster", source
                        )
                        posters += 1
                        changed = True
                        print(f"    poster -> {movie.poster_key}")
                    except RuntimeError as exc:
                        print(f"    poster failed: {exc}")
                        skipped += 1

            if needs_banner:
                video_id = _youtube_id(movie.trailer_url)
                source = None
                if video_id:
                    source = await asyncio.to_thread(_youtube_still_url, video_id)
                if not source:
                    print("    skip banner (no YouTube still)")
                    skipped += 1
                else:
                    try:
                        movie.banner_key = await _upload_kind(
                            movie.slug, "banner", source
                        )
                        banners += 1
                        changed = True
                        print(f"    banner -> {movie.banner_key}")
                    except RuntimeError as exc:
                        print(f"    banner failed: {exc}")
                        skipped += 1

            if changed:
                await db.flush()

        await db.commit()
        print(f"Done. posters={posters}, banners={banners}, skipped={skipped}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
