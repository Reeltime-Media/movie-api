"""
Seed (or replace) a single movie's banner image in R2 + the content table.

Uploads a local image to R2 under `movies/{slug}/banner.{ext}` (the standard
key layout) and points the movie's `content.banner_key` at it.

DRY RUN by default — shows the target DB, the resolved R2 key, and the movie's
current banner_key WITHOUT uploading or writing. Pass --commit to actually do it.

    # preview (no changes):
    python seed_content_banner.py the-last-drive /path/to/banner.jpg

    # apply (uploads to R2 + updates the DB):
    python seed_content_banner.py the-last-drive /path/to/banner.jpg --commit

    # inside Docker:
    docker compose exec api python seed_content_banner.py <slug> <image> --commit
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import database_connection_label, sqlalchemy_engine_kwargs
from app.models.content import Content
from app.services import storage
from app.services.r2_keys import movie_banner_key

CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _content_type(image_path: Path) -> str:
    ext = image_path.suffix.lower().lstrip(".")
    content_type = CONTENT_TYPES.get(ext)
    if not content_type:
        raise SystemExit(
            f"Unsupported image type '.{ext}'. Use one of: {', '.join(sorted(CONTENT_TYPES))}"
        )
    return content_type


async def seed(slug: str, image_path: Path, commit: bool) -> None:
    if not image_path.is_file():
        raise SystemExit(f"Image not found: {image_path}")

    content_type = _content_type(image_path)
    key = movie_banner_key(slug, content_type)
    settings = get_settings()

    print(f"DB target : {database_connection_label(settings.effective_database_url)}")
    print(f"Image     : {image_path}  ({image_path.stat().st_size:,} bytes, {content_type})")
    print(f"R2 key    : {key}")
    print(f"Public URL: {storage.public_url(key)}")

    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            movie = await db.scalar(select(Content).where(Content.slug == slug))
            if movie is None:
                raise SystemExit(f"No content row with slug '{slug}'.")

            print(f"Movie     : {movie.title!r}  (current banner_key={movie.banner_key!r})")

            if not commit:
                print("\nDRY RUN — nothing uploaded or written. Re-run with --commit to apply.")
                return

            with image_path.open("rb") as fh:
                storage.upload_fileobj(fh, key, content_type=content_type)
            print(f"Uploaded to R2: {key}")

            movie.banner_key = key
            await db.commit()
            print(f"Updated content.banner_key -> {key}")
    finally:
        await engine.dispose()


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--commit"]
    commit = "--commit" in sys.argv[1:]
    if len(args) != 2:
        raise SystemExit(
            "Usage: python seed_content_banner.py <slug> <image_path> [--commit]"
        )
    asyncio.run(seed(args[0], Path(args[1]).expanduser(), commit))


if __name__ == "__main__":
    main()
