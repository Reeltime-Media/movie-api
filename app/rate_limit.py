from __future__ import annotations

import logging
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)


def _storage_uri() -> str | None:
    """Use Redis for SlowAPI counters when REDIS_URL is set (shared across workers)."""
    url = (os.environ.get("REDIS_URL") or "").strip()
    return url or None


def build_limiter() -> Limiter:
    uri = _storage_uri()
    if uri:
        try:
            return Limiter(key_func=get_remote_address, storage_uri=uri)
        except Exception as exc:
            logger.warning(
                "SlowAPI Redis storage unavailable (%s) — falling back to in-memory",
                exc,
            )
    return Limiter(key_func=get_remote_address)


limiter = build_limiter()
