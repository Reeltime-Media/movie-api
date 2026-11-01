"""Seed Domnak Akum EP11 podcast from local extracted assets (one-shot).

    cd movie-api
    PYTHONPATH=. python seed/seed_domnak_akum_podcast.py \
      --audio /tmp/reeltime-podcast-seed/assets/audio.mp3 \
      --poster /tmp/reeltime-podcast-seed/assets/poster.png
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import clear_settings_cache, get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.content import Content
from app.services import r2_keys, storage
from app.services.content_slug import unique_content_slug
from app.services.image_process import optimize_r2_image
from app.services.runtime import apply_runtime_minutes

TITLE = "សឹកអាគមគ្រូនិងសិស្ស"
TITLE_KM = "សឹកអាគមគ្រូនិងសិស្ស"
DESCRIPTION = (
    "តំណាក់អាគម៚ — Domnak Akum. Episode 054 / EP11 "
    "(seeded from Drive YouTube master; audio extracted for podcast playback)."
)


async def seed(audio_path: Path, poster_path: Path) -> None:
    clear_settings_cache()
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(
            settings.effective_database_url,
            debug=False,
            # Skip project CA — local macOS often fails chain verify on Supabase.
            ssl_root_cert=None,
            allow_insecure_ssl=True,
        ),
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        existing = await db.scalar(
            select(Content.id).where(
                Content.type == "podcast",
                Content.title == TITLE,
            )
        )
        if existing:
            print(f"Already seeded: {existing}")
            await engine.dispose()
            return

        slug = await unique_content_slug(TITLE, db)
        audio_key = r2_keys.podcast_audio_key(slug, "audio/mpeg")
        poster_key = r2_keys.podcast_poster_key(slug, "image/png")

        print(f"Uploading audio → {audio_key}")
        with audio_path.open("rb") as fh:
            storage.upload_fileobj(fh, audio_key, content_type="audio/mpeg")

        print(f"Uploading poster → {poster_key}")
        with poster_path.open("rb") as fh:
            storage.upload_fileobj(fh, poster_key, content_type="image/png")

        poster_key = await optimize_r2_image(poster_key, kind="poster")
        print(f"Optimized poster → {poster_key}")

        podcast = Content(
            id=uuid.uuid4(),
            type="podcast",
            slug=slug,
            title=TITLE,
            title_km=TITLE_KM,
            description=DESCRIPTION,
            genres=["Horror"],
            price_usd=Decimal("0"),
            is_free=False,
            status="published",
            is_published=True,
            transcode_status="ready",
            audio_key=audio_key,
            poster_key=poster_key,
        )
        # ~37m 41s from source
        apply_runtime_minutes(podcast, 38)
        db.add(podcast)
        await db.commit()
        await db.refresh(podcast)
        print(f"Published podcast id={podcast.id} slug={podcast.slug}")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--poster", type=Path, required=True)
    args = parser.parse_args()
    if not args.audio.is_file():
        raise SystemExit(f"Missing audio: {args.audio}")
    if not args.poster.is_file():
        raise SystemExit(f"Missing poster: {args.poster}")
    asyncio.run(seed(args.audio, args.poster))


if __name__ == "__main__":
    main()
