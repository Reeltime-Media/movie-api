"""
Batch-compress poster/banner images already stored in R2 and fix DB keys.

Dry run by default:
  python scripts/optimize_r2_images.py

Apply changes:
  python scripts/optimize_r2_images.py --commit

Docker:
  docker compose exec api python scripts/optimize_r2_images.py --commit
"""

from __future__ import annotations

import argparse
import asyncio
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


async def _optimize_key(key: str | None, *, kind: str) -> str | None:
    if not key or not is_image_object_key(key):
        return key
    if not storage.object_exists(key):
        print(f"  skip missing: {key}")
        return key
    return await optimize_r2_image(key, kind=kind)  # type: ignore[arg-type]


async def main(commit: bool) -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        **sqlalchemy_engine_kwargs(settings),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print(f"Database: {database_connection_label(settings)}")

    async with session_factory() as db:
        movies = (await db.execute(select(Content))).scalars().all()
        series_rows = (await db.execute(select(Series))).scalars().all()
        promos = (await db.execute(select(PromotionBanner))).scalars().all()

        changed = 0
        for movie in movies:
            new_poster = await _optimize_key(movie.poster_key, kind="poster")
            new_banner = await _optimize_key(movie.banner_key, kind="banner")
            if new_poster != movie.poster_key or new_banner != movie.banner_key:
                print(
                    f"movie {movie.slug}: poster {movie.poster_key!r} -> {new_poster!r}, "
                    f"banner {movie.banner_key!r} -> {new_banner!r}"
                )
                if commit:
                    movie.poster_key = new_poster
                    movie.banner_key = new_banner
                changed += 1

        for row in series_rows:
            new_poster = await _optimize_key(row.poster_key, kind="poster")
            new_banner = await _optimize_key(row.banner_key, kind="banner")
            if new_poster != row.poster_key or new_banner != row.banner_key:
                print(
                    f"series {row.slug}: poster {row.poster_key!r} -> {new_poster!r}, "
                    f"banner {row.banner_key!r} -> {new_banner!r}"
                )
                if commit:
                    row.poster_key = new_poster
                    row.banner_key = new_banner
                changed += 1

        for promo in promos:
            new_image = await _optimize_key(promo.image_key, kind="banner")
            if new_image != promo.image_key:
                print(f"promo {promo.id}: image {promo.image_key!r} -> {new_image!r}")
                if commit:
                    promo.image_key = new_image
                changed += 1

        if commit and changed:
            await db.commit()

    await engine.dispose()
    mode = "committed" if commit else "dry run"
    print(f"Done ({mode}): {changed} record(s) with optimized image keys.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compress existing R2 poster/banner images.")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Write optimized keys back to the database (R2 objects are always updated).",
    )
    args = parser.parse_args()
    asyncio.run(main(commit=args.commit))
