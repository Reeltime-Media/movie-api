"""Short-lived Bakong check cache — shared by client poll + sweeper.

Avoids hammering payment-bakong/NBC for the same unpaid md5 within a few seconds.
Paid results are cached longer so settle/fulfill races stay cheap.
"""

from __future__ import annotations

import time
from threading import Lock

# Unpaid checks are noisy (poll every ~1.5–4s + sweeper). Cache negatives briefly.
_UNPAID_TTL_SECONDS = 2.0
# Paid is terminal for that md5 — keep long enough to cover settle + sibling walks.
_PAID_TTL_SECONDS = 60.0
# Skip sweeper settle when a client poll checked this intent recently.
_INTENT_POLL_TTL_SECONDS = 8.0

_lock = Lock()
_md5_cache: dict[str, tuple[bool, float]] = {}
_intent_polled_at: dict[str, float] = {}


def _prune(now: float) -> None:
    stale_md5 = [k for k, (_, exp) in _md5_cache.items() if exp <= now]
    for k in stale_md5:
        del _md5_cache[k]
    stale_intent = [k for k, exp in _intent_polled_at.items() if exp <= now]
    for k in stale_intent:
        del _intent_polled_at[k]


def get_cached_md5_paid(md5: str) -> bool | None:
    """Return cached paid flag, or None on miss/expiry."""
    if not md5:
        return None
    now = time.monotonic()
    with _lock:
        hit = _md5_cache.get(md5)
        if not hit:
            return None
        paid, exp = hit
        if exp <= now:
            del _md5_cache[md5]
            return None
        return paid


def set_cached_md5_paid(md5: str, paid: bool) -> None:
    if not md5:
        return
    now = time.monotonic()
    ttl = _PAID_TTL_SECONDS if paid else _UNPAID_TTL_SECONDS
    with _lock:
        _prune(now)
        _md5_cache[md5] = (paid, now + ttl)


def mark_intent_polled(intent_id: str) -> None:
    """Record that a client poll just checked this intent (sweeper can skip)."""
    if not intent_id:
        return
    now = time.monotonic()
    with _lock:
        _prune(now)
        _intent_polled_at[intent_id] = now + _INTENT_POLL_TTL_SECONDS


def was_intent_recently_polled(intent_id: str) -> bool:
    if not intent_id:
        return False
    now = time.monotonic()
    with _lock:
        exp = _intent_polled_at.get(intent_id)
        if exp is None:
            return False
        if exp <= now:
            del _intent_polled_at[intent_id]
            return False
        return True
