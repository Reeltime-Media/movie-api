"""Tiny in-process TTL cache for read-heavy, rarely-changing catalog
endpoints (movie/series listings, home rails). Each Uvicorn worker has its
own dict — that is fine; the goal is skipping a DB round-trip on the hot
path, not a globally coherent cache.

Trade-off: an admin publishing/editing a title can take up to the TTL
to show up in list responses. Deliberately short (30s) to keep that
window small while still avoiding a DB round-trip on every request.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

_CACHE: dict[str, tuple[float, Any]] = {}

CATALOG_TTL_SECONDS = 30

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


def cache_set(
    key: str, value: Any, *, ttl_seconds: float, now: float | None = None
) -> None:
    start = now if now is not None else time.monotonic()
    _CACHE[key] = (start + ttl_seconds, value)


async def cache_get_or_set(
    key: str,
    factory: Callable[[], Awaitable[T]],
    *,
    ttl_seconds: float = CATALOG_TTL_SECONDS,
) -> T:
    cached = cache_get(key)
    if cached is not None:
        return cached
    value = await factory()
    cache_set(key, value, ttl_seconds=ttl_seconds)
    return value
