"""In-process Bakong settle sweeper — fulfills paid intents without client polls.

NBC allows ~100 check_transaction_by_md5 calls per developer token per day.
This sweeper must stay tiny: a few recent intents only, sequential checks,
long backoff on rate-limit, never stampede unpaid abandoned QRs.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.payment_intent import PaymentIntent
from app.services import bakong
from app.services.bakong_check_cache import (
    STATUS_PAID,
    STATUS_UNKNOWN,
    was_intent_recently_polled,
)
from app.services.bakong_quota import bakong_checks_blocked, note_bakong_rate_limited
from app.services.bakong_settle import settle_bakong_intent_if_paid

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_lock_file = None
_SWEEP_LOCK_PATH = Path("/tmp/reeltime-bakong-sweeper.lock")
_RATE_LIMIT_BACKOFF_SECONDS = 60 * 60
_rate_limit_until_monotonic = 0.0


async def sweep_pending_bakong_intents() -> int:
    """Check a small batch of recent pending Bakong intents. Returns settled count."""
    global _rate_limit_until_monotonic

    now_mono = time.monotonic()
    if now_mono < _rate_limit_until_monotonic or bakong_checks_blocked():
        return 0

    settings = get_settings()
    now = datetime.now(timezone.utc)
    window_minutes = min(45, max(10, settings.bakong_sweeper_window_minutes))
    batch_size = min(3, max(1, settings.bakong_sweeper_batch_size))
    window_start = now - timedelta(minutes=window_minutes)
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
            .order_by(qr_age.desc())
            .limit(batch_size)
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

        rate_limited = False
        for intent in intents:
            if bakong_checks_blocked():
                rate_limited = True
                break
            try:
                status = await bakong.probe_khqr_status(intent.bakong_md5 or "")
            except Exception:
                logger.exception(
                    "Bakong sweeper check failed for intent_id=%s", intent.intent_id
                )
                continue

            if status == STATUS_UNKNOWN:
                rate_limited = True
                break

            paid = status == STATUS_PAID
            if (
                not paid
                and intent.bakong_prev_md5
                and intent.bakong_prev_md5 != intent.bakong_md5
            ):
                prev = await bakong.probe_khqr_status(intent.bakong_prev_md5)
                if prev == STATUS_UNKNOWN:
                    rate_limited = True
                    break
                paid = prev == STATUS_PAID

            if not paid:
                continue

            try:
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

        if rate_limited:
            note_bakong_rate_limited(cooldown_seconds=_RATE_LIMIT_BACKOFF_SECONDS)
            _rate_limit_until_monotonic = time.monotonic() + _RATE_LIMIT_BACKOFF_SECONDS
            logger.warning(
                "Bakong sweeper saw rate-limit/unknown — pausing %.0fs to save NBC quota",
                _RATE_LIMIT_BACKOFF_SECONDS,
            )

    if settled:
        logger.info("Bakong sweeper settled %s intent(s)", settled)
    return settled


async def _sweeper_loop() -> None:
    settings = get_settings()
    interval = max(120, settings.bakong_sweeper_interval_seconds)
    logger.info(
        "Bakong settle sweeper started (interval=%ss, window_cap=45min, batch_cap=3)",
        interval,
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
    if _task is not None:
        return
    _SWEEP_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(_SWEEP_LOCK_PATH, "a+", encoding="utf-8")
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
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    if _lock_file is not None:
        try:
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            _lock_file.close()
            _lock_file = None
    logger.info("Bakong settle sweeper stopped")
