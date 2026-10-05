"""Short-lived Bakong check cache — shared by client poll + sweeper.

Avoids hammering payment-bakong/NBC for the same unpaid md5 within a few seconds.
Paid results are cached longer so settle/fulfill races stay cheap.
"""

from __future__ import annotations

import time
from threading import Lock

# NBC daily check quota is ~100/token. Keep unpaid cache near the UI poll
# interval so open tabs feel snappy (~5–10s) without a check every second.
_UNPAID_TTL_SECONDS = 8.0
_RATE_LIMIT_TTL_SECONDS = 120.0
# Paid is terminal for that md5 — keep long enough to cover settle + sibling walks.
_PAID_TTL_SECONDS = 60.0
# Skip sweeper settle when a client poll checked this intent recently.
_INTENT_POLL_TTL_SECONDS = 12.0
# One stuck checkout tab must not burn a whole NBC token (~100/day).
_MAX_NBC_CHECKS_PER_INTENT = 40
# Cap resets after this window so a regenerated QR can be verified again.
_INTENT_NBC_CHECK_WINDOW_SECONDS = 60 * 60

_lock = Lock()
# paid | unpaid | unknown
_md5_cache: dict[str, tuple[str, float]] = {}
_intent_polled_at: dict[str, float] = {}
# intent_id -> (count, window_started_at)
_intent_nbc_checks: dict[str, tuple[int, float]] = {}

STATUS_PAID = "paid"
STATUS_UNPAID = "unpaid"
STATUS_UNKNOWN = "unknown"


def _prune(now: float) -> None:
    stale_md5 = [k for k, (_, exp) in _md5_cache.items() if exp <= now]
    for k in stale_md5:
        del _md5_cache[k]
    stale_intent = [k for k, exp in _intent_polled_at.items() if exp <= now]
    for k in stale_intent:
        del _intent_polled_at[k]


def ttl_for_check(*, paid: bool, rate_limited: bool = False) -> float:
    if paid:
        return _PAID_TTL_SECONDS
    if rate_limited:
        return _RATE_LIMIT_TTL_SECONDS
    return _UNPAID_TTL_SECONDS


def ttl_for_status(status: str) -> float:
    if status == STATUS_PAID:
        return _PAID_TTL_SECONDS
    if status == STATUS_UNKNOWN:
        return _RATE_LIMIT_TTL_SECONDS
    return _UNPAID_TTL_SECONDS


def get_cached_md5_status(md5: str) -> str | None:
    if not md5:
        return None
    now = time.monotonic()
    with _lock:
        hit = _md5_cache.get(md5)
        if not hit:
            return None
        status, exp = hit
        if exp <= now:
            del _md5_cache[md5]
            return None
        return status


def get_cached_md5_paid(md5: str) -> bool | None:
    """Return cached paid flag, or None on miss/expiry."""
    status = get_cached_md5_status(md5)
    if status is None:
        return None
    return status == STATUS_PAID


def set_cached_md5_status(md5: str, status: str, *, ttl: float | None = None) -> None:
    if not md5:
        return
    now = time.monotonic()
    if ttl is None:
        ttl = ttl_for_status(status)
    with _lock:
        _prune(now)
        _md5_cache[md5] = (status, now + ttl)


def set_cached_md5_paid(md5: str, paid: bool, *, ttl: float | None = None) -> None:
    if not md5:
        return
    status = STATUS_PAID if paid else STATUS_UNPAID
    if ttl is None:
        ttl = _PAID_TTL_SECONDS if paid else _UNPAID_TTL_SECONDS
    set_cached_md5_status(md5, status, ttl=ttl)


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


def intent_nbc_check_count(intent_id: str) -> int:
    if not intent_id:
        return 0
    now = time.monotonic()
    with _lock:
        entry = _intent_nbc_checks.get(intent_id)
        if not entry:
            return 0
        used, started = entry
        if now - started >= _INTENT_NBC_CHECK_WINDOW_SECONDS:
            del _intent_nbc_checks[intent_id]
            return 0
        return int(used)


def consume_intent_nbc_check(
    intent_id: str,
    *,
    max_checks: int = _MAX_NBC_CHECKS_PER_INTENT,
) -> bool:
    """Reserve one NBC network check for this intent. False when over cap."""
    if not intent_id:
        return True
    limit = max(1, int(max_checks))
    now = time.monotonic()
    with _lock:
        entry = _intent_nbc_checks.get(intent_id)
        if entry is None or now - entry[1] >= _INTENT_NBC_CHECK_WINDOW_SECONDS:
            _intent_nbc_checks[intent_id] = (1, now)
            used = 1
        else:
            used = int(entry[0]) + 1
            if used > limit:
                return False
            _intent_nbc_checks[intent_id] = (used, entry[1])
        # Soft prune if map grows (abandoned checkouts).
        if len(_intent_nbc_checks) > 2000:
            drop = list(_intent_nbc_checks.keys())[:500]
            for key in drop:
                del _intent_nbc_checks[key]
        return True


def reset_intent_nbc_checks(intent_id: str | None = None) -> None:
    """Reset check budget for one intent (e.g. after QR regenerate), or all."""
    with _lock:
        if intent_id:
            _intent_nbc_checks.pop(intent_id, None)
        else:
            _intent_nbc_checks.clear()


def clear_intent_nbc_checks() -> None:
    """Test helper."""
    reset_intent_nbc_checks()
