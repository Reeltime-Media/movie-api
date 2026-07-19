"""In-process Bakong settle sweeper — fulfills paid intents without client polls."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.payment_intent import PaymentIntent
from app.services.bakong_settle import settle_bakong_intent_if_paid

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


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
        intents = list(result.scalars().all())
        for intent in intents:
            try:
                if await settle_bakong_intent_if_paid(db, intent):
                    settled += 1
            except Exception:
                logger.exception(
                    "Bakong sweeper failed for intent_id=%s", intent.intent_id
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
        "Bakong settle sweeper started (interval=%ss, window=%smin, batch=%s)",
        interval,
        settings.bakong_sweeper_window_minutes,
        settings.bakong_sweeper_batch_size,
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
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_sweeper_loop(), name="bakong-settle-sweeper")


async def stop_bakong_sweeper() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    logger.info("Bakong settle sweeper stopped")
