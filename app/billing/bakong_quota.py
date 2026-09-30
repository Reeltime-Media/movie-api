"""Global Bakong NBC check circuit breaker.

When payment-bakong reports daily limit / rate-limit, stop issuing new NBC
checks from movie-api for a while. Poll/sweeper return pending without
burning the remaining quota; playback authorize can still try after the
cooldown so paid customers unlock.

Blocked-until is stored in Redis when REDIS_URL is set so all Uvicorn
workers share one circuit; otherwise an in-process fallback is used.
"""

from __future__ import annotations

import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)

# Match payment-bakong pause: do not keep probing after error 17.
_DEFAULT_COOLDOWN_SECONDS = 60 * 60
_REDIS_KEY = "bakong:nbc_blocked_until"
_lock = Lock()
_blocked_until_monotonic = 0.0
_redis_sync = None
_redis_failed = False


def _sync_redis():
    """Lazy sync Redis client (quota checks are sync and on the hot path)."""
    global _redis_sync, _redis_failed
    if _redis_failed:
        return None
    if _redis_sync is not None:
        return _redis_sync
    from app.config import get_settings

    url = (get_settings().redis_url or "").strip()
    if not url:
        return None
    try:
        import redis

        _redis_sync = redis.from_url(
            url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
            decode_responses=True,
        )
        return _redis_sync
    except Exception as exc:
        _redis_failed = True
        logger.warning("bakong_quota: Redis unavailable (%s) — in-process only", exc)
        return None


def note_bakong_rate_limited(*, cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS) -> None:
    global _blocked_until_monotonic
    cooldown = max(60.0, cooldown_seconds)
    until_mono = time.monotonic() + cooldown
    with _lock:
        if until_mono > _blocked_until_monotonic:
            _blocked_until_monotonic = until_mono

    client = _sync_redis()
    if client is None:
        return
    try:
        until_unix = time.time() + cooldown
        # Keep the longer of the existing Redis deadline and this one.
        existing = client.get(_REDIS_KEY)
        if existing is not None:
            try:
                until_unix = max(until_unix, float(existing))
            except (TypeError, ValueError):
                pass
        client.set(_REDIS_KEY, str(until_unix), ex=int(cooldown) + 60)
    except Exception as exc:
        logger.warning("bakong_quota: Redis set failed: %s", exc)


def bakong_checks_blocked() -> bool:
    client = _sync_redis()
    if client is not None:
        try:
            raw = client.get(_REDIS_KEY)
            if raw is not None and float(raw) > time.time():
                return True
        except Exception as exc:
            logger.warning("bakong_quota: Redis get failed: %s", exc)

    with _lock:
        return time.monotonic() < _blocked_until_monotonic


def bakong_checks_blocked_remaining_seconds() -> float:
    client = _sync_redis()
    if client is not None:
        try:
            raw = client.get(_REDIS_KEY)
            if raw is not None:
                return max(0.0, float(raw) - time.time())
        except Exception as exc:
            logger.warning("bakong_quota: Redis get failed: %s", exc)

    with _lock:
        return max(0.0, _blocked_until_monotonic - time.monotonic())


def clear_bakong_rate_limit() -> None:
    global _blocked_until_monotonic, _redis_sync, _redis_failed
    with _lock:
        _blocked_until_monotonic = 0.0
    client = _sync_redis()
    if client is not None:
        try:
            client.delete(_REDIS_KEY)
        except Exception:
            pass
    # Allow tests to re-bind Redis after clear.
    _redis_sync = None
    _redis_failed = False
