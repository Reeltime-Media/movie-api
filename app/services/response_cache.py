"""Tiny in-process TTL cache for read-heavy, rarely-changing catalog
endpoints (movie/series listings). The API runs as a single Uvicorn
process (see docker-compose.yml — no --workers), so a plain in-memory
dict is correctly shared across every request with no need for Redis or
cross-process coordination.

Trade-off: an admin publishing/editing a title can take up to the TTL
to show up in list responses. Deliberately short (30s) to keep that
window small while still avoiding a DB round-trip on every request.
"""

import time
from typing import Any

_CACHE: dict[str, tuple[float, Any]] = {}


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
