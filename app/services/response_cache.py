"""TTL cache for read-heavy catalog endpoints (movie/series lists, home rails).

L1: in-process dict (per Uvicorn worker) — sync helpers for unit tests and
hot same-worker hits.

L2: optional Redis via ``shared_cache`` — shared across workers when
``REDIS_URL`` is set. Misses fall through to the DB; Redis failures are
non-fatal (same as HLS playlist caching).

Trade-off: an admin publishing/editing a title can take up to the TTL
to show up in list responses. Deliberately short (30s).
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.services import shared_cache

_CACHE: dict[str, tuple[float, Any]] = {}

CATALOG_TTL_SECONDS = 30
_REDIS_KEY_PREFIX = "catalog:"

T = TypeVar("T")


def cache_get(key: str, *, now: float | None = None) -> Any | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if (now if now is not None else time.monotonic()) >= expires_at:
        del _CACHE[key]
        return None
    return value


def cache_set(key: str, value: Any, *, ttl_seconds: float, now: float | None = None) -> None:
    start = now if now is not None else time.monotonic()
    _CACHE[key] = (start + ttl_seconds, value)


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


async def cache_get_async(key: str) -> Any | None:
    local = cache_get(key)
    if local is not None:
        return local
    raw = await shared_cache.cache_get_bytes(_REDIS_KEY_PREFIX + key)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    # Populate L1 so the next hit on this worker skips Redis.
    cache_set(key, value, ttl_seconds=CATALOG_TTL_SECONDS)
    return value


async def cache_set_async(
    key: str, value: Any, *, ttl_seconds: float = CATALOG_TTL_SECONDS
) -> None:
    cache_set(key, value, ttl_seconds=ttl_seconds)
    payload = _to_jsonable(value)
    try:
        await shared_cache.cache_set_bytes(
            _REDIS_KEY_PREFIX + key,
            json.dumps(payload, default=str).encode("utf-8"),
            ttl_seconds,
        )
    except Exception:
        # shared_cache already logs; never fail the request on cache write.
        pass


async def cache_get_or_set(
    key: str,
    factory: Callable[[], Awaitable[T]],
    *,
    ttl_seconds: float = CATALOG_TTL_SECONDS,
) -> T:
    cached = await cache_get_async(key)
    if cached is not None:
        return cached
    value = await factory()
    await cache_set_async(key, value, ttl_seconds=ttl_seconds)
    return value
