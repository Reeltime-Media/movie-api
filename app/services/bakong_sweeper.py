"""In-process Bakong settle sweeper — fulfills paid intents without client polls."""

from __future__ import annotations

import asyncio
import fcntl
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.payment_intent import PaymentIntent
from app.services.bakong_check_cache import was_intent_recently_polled
from app.services.bakong_settle import bakong_md5s_paid, settle_bakong_intent_if_paid

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_lock_file = None
_SWEEP_LOCK_PATH = Path("/tmp/reeltime-bakong-sweeper.lock")
# Cap concurrent NBC checks so a big batch cannot stampede the gateway.
_SWEEP_CONCURRENCY = 5


async def sweep_pending_bakong_intents() -> int:
    """Check a batch of recent pending Bakong intents. Returns settled count."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=settings.bakong_sweeper_window_minutes)
    settled = 0
    qr_age = func.coalesce(
        PaymentIntent.bakong_qr_created_at, PaymentIntent.created_at
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PaymentIntent)
            .where(
                PaymentIntent.method == "bakong",
                PaymentIntent.status == "pending",
                PaymentIntent.bakong_md5.is_not(None),
                qr_age >= window_start,
            )
            .order_by(qr_age.asc())
            .limit(settings.bakong_sweeper_batch_size)
            .with_for_update(skip_locked=True)
        )
        intents = [
            intent
            for intent in result.scalars().all()
            if not was_intent_recently_polled(intent.intent_id)
        ]
        if not intents:
            await db.rollback()
            return 0

        # Parallelize Bakong HTTP checks only — AsyncSession is not concurrency-safe.
        sem = asyncio.Semaphore(_SWEEP_CONCURRENCY)

        async def _check(intent: PaymentIntent) -> tuple[PaymentIntent, bool]:
            async with sem:
                try:
                    return intent, await bakong_md5s_paid(intent)
                except Exception:
                    logger.exception(
                        "Bakong sweeper check failed for intent_id=%s", intent.intent_id
                    )
                    return intent, False

        checks = await asyncio.gather(*[_check(intent) for intent in intents])
        for intent, paid in checks:
            if not paid:
                continue
            try:
                # Re-enter settle so fulfillment + status update stay on one session.
                if await settle_bakong_intent_if_paid(db, intent):
                    settled += 1
            except Exception:
                logger.exception(
                    "Bakong sweeper fulfill failed for intent_id=%s", intent.intent_id
                )

        if settled:
            await db.commit()
        else:
            await db.rollback()

    if settled:
        logger.info("Bakong sweeper settled %s intent(s)", settled)
    return settled


async def _sweeper_loop() -> None:
    settings = get_settings()
    interval = max(5, settings.bakong_sweeper_interval_seconds)
    logger.info(
        "Bakong settle sweeper started (interval=%ss, window=%smin, batch=%s, concurrency=%s)",
        interval,
        settings.bakong_sweeper_window_minutes,
        settings.bakong_sweeper_batch_size,
        _SWEEP_CONCURRENCY,
    )
    while True:
        try:
            await sweep_pending_bakong_intents()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Bakong sweeper tick failed")
        await asyncio.sleep(interval)


def start_bakong_sweeper() -> None:
    """Start the sweeper in at most one Uvicorn worker (file lock)."""
    global _task, _lock_file
    if _task is not None and not _task.done():
        return
    lock_file = _SWEEP_LOCK_PATH.open("a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        logger.info("Bakong sweeper already running in another worker")
        return
    _lock_file = lock_file
    _task = asyncio.create_task(_sweeper_loop(), name="bakong-settle-sweeper")


async def stop_bakong_sweeper() -> None:
    global _task, _lock_file
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    if _lock_file is not None:
        try:
            _lock_file.close()
        except OSError:
            pass
        _lock_file = None
    logger.info("Bakong settle sweeper stopped")
