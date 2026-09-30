"""Poll payment-bakong /health and Telegram-alert when NBC checks are down.

Runs only while ``bakong_nbc_settle_enabled`` and a remote Bakong service URL
are configured. At most one alert per ICT day (same ops chat as daily limit).

Ownership: Redis lock (or flock fallback) so multi-worker deploys do not
duplicate polls / alerts.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.services.distributed_lock import HeldLock, try_acquire

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 180.0
_task: asyncio.Task | None = None
_held_lock: HeldLock | None = None
_LOCK_NAME = "bakong:health-monitor"
_LOCK_TTL_SECONDS = 240


async def check_once_and_alert() -> bool:
    """Return True if checks look unavailable (and alert may have been sent)."""
    settings = get_settings()
    if not settings.bakong_nbc_settle_enabled:
        return False

    from app.services.bakong import fetch_remote_health

    body = await fetch_remote_health()
    if body is None:
        return False

    available = body.get("bakong_checks_available")
    if available is True:
        return False
    if available is False:
        from app.services.telegram import notify_bakong_checks_unavailable

        paused = body.get("bakong_tokens_paused")
        total = body.get("bakong_token_count")
        await notify_bakong_checks_unavailable(
            tokens_paused=paused if isinstance(paused, int) else None,
            token_count=total if isinstance(total, int) else None,
        )
        return True
    return False


async def _monitor_loop() -> None:
    logger.info("Bakong health monitor started (interval=%ss)", int(_POLL_INTERVAL_SECONDS))
    # First pass soon after boot so ops hear about a dead quota quickly.
    await asyncio.sleep(15.0)
    while True:
        try:
            if _held_lock is not None and not _held_lock.refresh():
                logger.warning("Bakong health monitor lost ownership lock — stopping")
                break
            await check_once_and_alert()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Bakong health monitor pass failed")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


def start_bakong_health_monitor() -> bool:
    """Start monitor in at most one process. Returns True if this process owns it."""
    global _task, _held_lock
    settings = get_settings()
    if not settings.bakong_nbc_settle_enabled:
        logger.info("Bakong health monitor not started (nbc settle off)")
        return False
    if not (settings.bakong_service_url or "").strip():
        logger.info("Bakong health monitor not started (no BAKONG_SERVICE_URL)")
        return False
    if _task is not None and not _task.done():
        return True

    held = try_acquire(
        _LOCK_NAME,
        ttl_seconds=_LOCK_TTL_SECONDS,
        flock_path="/tmp/reeltime-bakong-health.lock",
    )
    if held is None:
        logger.info("Bakong health monitor already running elsewhere")
        return False
    _held_lock = held
    logger.info("Bakong health monitor lock acquired via %s", held.backend)
    _task = asyncio.create_task(_monitor_loop(), name="bakong-health-monitor")
    return True


async def stop_bakong_health_monitor() -> None:
    global _task, _held_lock
    if _task is None and _held_lock is None:
        return
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
