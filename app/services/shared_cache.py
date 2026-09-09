"""Optional Redis-backed byte cache shared across Uvicorn workers.

When REDIS_URL is empty or redis is unavailable, callers get None on get and
a no-op on set — fall back to their in-process dicts. That keeps local/dev
and the current 2-worker deploy working without Redis while still letting
production plug in Upstash later.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_redis: Any | None = None
_redis_failed = False


def _client():
    global _redis, _redis_failed
    if _redis_failed:
        return None
    if _redis is not None:
        return _redis
    url = (get_settings().redis_url or "").strip()
    if not url:
        return None
    try:
        import redis.asyncio as redis_async

        _redis = redis_async.from_url(
            url,
            encoding=None,
            decode_responses=False,
            socket_connect_timeout=1.5,
            socket_timeout=1.5,
        )
        return _redis
    except Exception as exc:
        _redis_failed = True
        logger.warning("shared_cache: Redis unavailable (%s) — using in-process only", exc)
        return None


async def cache_get_bytes(key: str) -> bytes | None:
    client = _client()
    if client is None:
        return None
    try:
        value = await client.get(key)
        if value is None:
            return None
        return value if isinstance(value, bytes) else bytes(value)
    except Exception as exc:
        logger.warning("shared_cache get failed key=%s: %s", key[:48], exc)
        return None


async def cache_set_bytes(key: str, value: bytes, ttl_seconds: float) -> None:
    client = _client()
    if client is None:
        return
    try:
        ttl = max(1, int(ttl_seconds))
        await client.set(key, value, ex=ttl)
    except Exception as exc:
        logger.warning("shared_cache set failed key=%s: %s", key[:48], exc)


async def close_shared_cache() -> None:
    global _redis, _redis_failed
    client = _redis
    _redis = None
    _redis_failed = False
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass
