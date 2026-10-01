"""Dedicated Bakong background process (sweeper + health monitor).

Run instead of (or in addition to) in-API loops:

  python -m app.workers.bakong

When using this worker, set BAKONG_RUN_BACKGROUND_IN_API=false on the API
so only one process owns the Redis/flock locks.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.config import get_settings
from app.services.bakong_health_monitor import (
    start_bakong_health_monitor,
    stop_bakong_health_monitor,
)
from app.services.bakong_sweeper import start_bakong_sweeper, stop_bakong_sweeper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("app.workers.bakong")


async def _run() -> None:
    settings = get_settings()
    started_any = False

    if settings.bakong_nbc_settle_enabled and settings.bakong_sweeper_enabled:
        if start_bakong_sweeper():
            started_any = True
    else:
        logger.info(
            "Sweeper not started (nbc_settle=%s sweeper=%s)",
            settings.bakong_nbc_settle_enabled,
            settings.bakong_sweeper_enabled,
        )

    if start_bakong_health_monitor():
        started_any = True

    if not started_any:
        logger.error("No Bakong background loops started — check config / locks")
        return

    stop = asyncio.Event()

    def _handle_signal(*_args) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop.set())

    logger.info("Bakong worker running — waiting for shutdown signal")
    await stop.wait()
    await stop_bakong_health_monitor()
    await stop_bakong_sweeper()
    from app.database import get_engine
    from app.services.bakong import close_http_client as close_bakong
    from app.services.shared_cache import close_shared_cache
    from app.services.telegram import close_http_client as close_telegram

    await close_bakong()
    await close_telegram()
    await close_shared_cache()
    await get_engine().dispose()
    logger.info("Bakong worker stopped")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
