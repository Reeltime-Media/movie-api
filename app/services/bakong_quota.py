"""Global Bakong NBC check circuit breaker.

When payment-bakong reports daily limit / rate-limit, stop issuing new NBC
checks from movie-api for a while. Poll/sweeper return pending without
burning the remaining quota; playback authorize can still try after the
cooldown so paid customers unlock.
"""

from __future__ import annotations

import time
from threading import Lock

# Match payment-bakong pause: do not keep probing after error 17.
_DEFAULT_COOLDOWN_SECONDS = 60 * 60
_lock = Lock()
_blocked_until_monotonic = 0.0


def note_bakong_rate_limited(*, cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS) -> None:
    global _blocked_until_monotonic
    until = time.monotonic() + max(60.0, cooldown_seconds)
    with _lock:
        if until > _blocked_until_monotonic:
            _blocked_until_monotonic = until


def bakong_checks_blocked() -> bool:
    with _lock:
        return time.monotonic() < _blocked_until_monotonic


def bakong_checks_blocked_remaining_seconds() -> float:
    with _lock:
        return max(0.0, _blocked_until_monotonic - time.monotonic())


def clear_bakong_rate_limit() -> None:
    global _blocked_until_monotonic
    with _lock:
        _blocked_until_monotonic = 0.0
