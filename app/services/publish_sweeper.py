"""Promote scheduled movies/series to published when publish_at is due and assets are ready."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.content import Content
from app.models.series import Series
from app.services.content_publish import (
    movie_is_publishable,
    promote_scheduled_movie_to_published,
)
from app.services.distributed_lock import HeldLock, try_acquire
from app.services.series_publish import (
    promote_scheduled_series_to_published,
    series_is_publishable,
)

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_held_lock: HeldLock | None = None
_LOCK_NAME = "publish:sweeper"
_LOCK_TTL_SECONDS = 120


async def sweep_due_scheduled_movies(*, limit: int = 25) -> int:
    """Publish due scheduled movies that are ready. Returns promoted count."""
    now = datetime.now(UTC)
    promoted = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Content)
            .where(
                Content.type == "single",
                Content.is_published.is_(False),
                Content.publish_at.is_not(None),
                Content.publish_at <= now,
            )
            .order_by(Content.publish_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        movies = list(result.scalars().all())
        if not movies:
            await db.rollback()
            return 0

        for movie in movies:
            if not await movie_is_publishable(db, movie):
                logger.info(
                    "Scheduled movie not ready yet id=%s slug=%s publish_at=%s",
                    movie.id,
                    movie.slug,
                    movie.publish_at,
                )
                continue
            promote_scheduled_movie_to_published(movie)
            promoted += 1
            logger.info("Published scheduled movie id=%s slug=%s", movie.id, movie.slug)

        if promoted:
            await db.commit()
        else:
            await db.rollback()

    return promoted


async def sweep_due_scheduled_series(*, limit: int = 25) -> int:
    """Publish due scheduled series that are ready. Returns promoted count."""
    now = datetime.now(UTC)
    promoted = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Series)
            .where(
                Series.is_published.is_(False),
                Series.publish_at.is_not(None),
                Series.publish_at <= now,
            )
            .order_by(Series.publish_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list(result.scalars().all())
        if not rows:
            await db.rollback()
            return 0

        for series in rows:
            if not series_is_publishable(series):
                logger.info(
                    "Scheduled series not ready yet id=%s slug=%s publish_at=%s",
                    series.id,
                    series.slug,
                    series.publish_at,
                )
                continue
            promote_scheduled_series_to_published(series)
            promoted += 1
            logger.info("Published scheduled series id=%s slug=%s", series.id, series.slug)

        if promoted:
            await db.commit()
        else:
            await db.rollback()

    return promoted


async def _sweeper_loop() -> None:
    settings = get_settings()
    interval = max(15, min(300, settings.publish_sweeper_interval_seconds))
    logger.info("Publish sweeper started (interval=%ss)", interval)
    while True:
        try:
            if _held_lock is not None and not _held_lock.refresh():
                logger.warning("Publish sweeper lost ownership lock — stopping loop")
                break
            await sweep_due_scheduled_movies()
            await sweep_due_scheduled_series()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Publish sweeper tick failed")
        await asyncio.sleep(interval)


def start_publish_sweeper() -> bool:
    global _task, _held_lock
    if _task is not None and not _task.done():
        return True
    held = try_acquire(
        _LOCK_NAME,
        ttl_seconds=_LOCK_TTL_SECONDS,
        flock_path="/tmp/reeltime-publish-sweeper.lock",
    )
    if held is None:
        logger.info("Publish sweeper already running elsewhere")
        return False
    _held_lock = held
    logger.info("Publish sweeper lock acquired via %s", held.backend)
    _task = asyncio.create_task(_sweeper_loop(), name="publish-sweeper")
    return True


async def stop_publish_sweeper() -> None:
    global _task, _held_lock
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    if _held_lock is not None:
        _held_lock.release()
        _held_lock = None
    logger.info("Publish sweeper stopped")
