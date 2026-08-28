"""
Batch-compress poster/banner images already stored in R2, write rail thumbs,
and fix DB keys.

For each unique catalog image this:
  1. Compresses the main asset to WebP (if needed)
  2. Ensures a rail thumb exists:
       poster.webp  -> poster-w400.webp
       banner.webp  -> banner-w480.webp

Apply R2 work + DB key updates:
  python scripts/optimize_r2_images.py --commit

Docker:
  docker compose exec api python scripts/optimize_r2_images.py --commit

Safe to re-run: existing thumbs are skipped; corrupt/missing sources are
logged once and skipped so the rest of the catalog can finish.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db_connect import database_connection_label, sqlalchemy_engine_kwargs
from app.models.content import Content
from app.models.promotion_banner import PromotionBanner
from app.models.series import Series
from app.services import storage
from app.services.image_process import is_image_object_key, optimize_r2_image

# Quiet the noisy per-broken-file stack traces from image_process — we print
# a one-line skip message ourselves.
logging.getLogger("app.services.image_process").setLevel(logging.ERROR)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def _log(msg: str) -> None:
    print(msg, flush=True)


async def _optimize_key(
    key: str | None,
    *,
    kind: str,
    cache: dict[str, str | None],
    broken: set[str],
) -> str | None:
    if not key or not is_image_object_key(key):
        return key
    if key in cache:
        return cache[key]
    if key in broken:
        return key

    try:
        if not storage.object_exists(key):
            _log(f"  skip missing: {key}")
            cache[key] = key
            return key
        result = await optimize_r2_image(key, kind=kind)  # type: ignore[arg-type]
        cache[key] = result
        return result
    except Exception as exc:  # noqa: BLE001 — keep batch going on bad assets
        _log(f"  skip broken {kind}: {key} ({exc})")
        broken.add(key)
        cache[key] = key
        return key


async def main(commit: bool) -> None:
    settings = get_settings()
    database_url = settings.effective_database_url
    engine = create_async_engine(
        database_url,
        **sqlalchemy_engine_kwargs(database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    _log(f"Database: {database_connection_label(database_url)}")
    _log(f"Mode: {'commit' if commit else 'dry run (R2 thumbs still written)'}")

    cache: dict[str, str | None] = {}
    broken: set[str] = set()

    async with session_factory() as db:
        movies = (await db.execute(select(Content))).scalars().all()
        series_rows = (await db.execute(select(Series))).scalars().all()
        promos = (await db.execute(select(PromotionBanner))).scalars().all()

        _log(
            f"Catalog: {len(movies)} content rows, {len(series_rows)} series, "
            f"{len(promos)} promos"
        )

        changed = 0

        for i, movie in enumerate(movies, start=1):
            if i == 1 or i % 50 == 0 or i == len(movies):
                _log(f"… content {i}/{len(movies)} (unique keys={len(cache)})")
            new_poster = await _optimize_key(
                movie.poster_key, kind="poster", cache=cache, broken=broken
            )
            new_banner = await _optimize_key(
                movie.banner_key, kind="banner", cache=cache, broken=broken
            )
            if new_poster != movie.poster_key or new_banner != movie.banner_key:
                _log(
                    f"content {movie.slug}: poster {movie.poster_key!r} -> {new_poster!r}, "
                    f"banner {movie.banner_key!r} -> {new_banner!r}"
                )
                if commit:
                    movie.poster_key = new_poster
                    movie.banner_key = new_banner
                changed += 1

        for i, row in enumerate(series_rows, start=1):
            if i == 1 or i % 25 == 0 or i == len(series_rows):
                _log(f"… series {i}/{len(series_rows)} (unique keys={len(cache)})")
            new_poster = await _optimize_key(
                row.poster_key, kind="poster", cache=cache, broken=broken
            )
            new_banner = await _optimize_key(
                row.banner_key, kind="banner", cache=cache, broken=broken
            )
            if new_poster != row.poster_key or new_banner != row.banner_key:
                _log(
                    f"series {row.slug}: poster {row.poster_key!r} -> {new_poster!r}, "
                    f"banner {row.banner_key!r} -> {new_banner!r}"
                )
                if commit:
                    row.poster_key = new_poster
                    row.banner_key = new_banner
                changed += 1

        for promo in promos:
            new_image = await _optimize_key(
                promo.image_key, kind="banner", cache=cache, broken=broken
            )
            if new_image != promo.image_key:
                _log(f"promo {promo.id}: image {promo.image_key!r} -> {new_image!r}")
                if commit:
                    promo.image_key = new_image
                changed += 1

        if commit and changed:
            await db.commit()

    await engine.dispose()
    mode = "committed" if commit else "dry run"
    _log(
        f"Done ({mode}): {changed} record(s) with optimized image keys, "
        f"{len(cache)} unique R2 keys processed, {len(broken)} broken skipped."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compress existing R2 poster/banner images and write rail thumbs."
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Write optimized keys back to the database (R2 objects/thumbs are always updated).",
    )
    args = parser.parse_args()
    asyncio.run(main(commit=args.commit))
