"""In-process Coming Soon sweeper — auto-publishes announced movies.

A movie in status='coming_soon' with a release_at date gets promoted to
'published' as soon as (a) release_at has passed and (b) its video is
ready (same gate as publishing any other movie — see content_publish.py).
Movies with no release_at (TBA) are never touched here; an admin must
publish those manually.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.content import Content
from app.services.content_publish import ensure_movie_publishable

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


async def promote_due_coming_soon() -> int:
    """Publish coming-soon movies whose release_at has passed and video is ready."""
    now = datetime.now(timezone.utc)
    promoted = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Content)
            .where(
                Content.type == "single",
                Content.status == "coming_soon",
                Content.release_at.is_not(None),
                Content.release_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
        movies = result.scalars().all()

        for movie in movies:
            try:
                await ensure_movie_publishable(db, movie)
            except HTTPException:
                continue  # video not uploaded/ready yet — retry next sweep
            movie.status = "published"
            movie.is_published = True
            promoted += 1

        if promoted:
            await db.commit()
        else:
            await db.rollback()

    if promoted:
        logger.info("Coming Soon sweeper promoted %s movie(s)", promoted)
    return promoted


async def _sweeper_loop() -> None:
    settings = get_settings()
    interval = max(5, settings.coming_soon_sweeper_interval_seconds)
    logger.info("Coming Soon sweeper started (interval=%ss)", interval)
    while True:
        try:
            await promote_due_coming_soon()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Coming Soon sweeper tick failed")
        await asyncio.sleep(interval)


def start_coming_soon_sweeper() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_sweeper_loop(), name="coming-soon-sweeper")


async def stop_coming_soon_sweeper() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    logger.info("Coming Soon sweeper stopped")
