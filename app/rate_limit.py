from __future__ import annotations

import logging
import os

from slowapi import Limiter

logger = logging.getLogger(__name__)


def _storage_uri() -> str | None:
    """Use Redis for SlowAPI counters when REDIS_URL is set (shared across workers)."""
    url = (os.environ.get("REDIS_URL") or "").strip()
    return url or None


def _rate_limit_key(request) -> str:
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            try:
                from app.core.security import decode_access_token

                payload = decode_access_token(token)
                sid = (payload.get("sid") or "").strip()
                sub = (payload.get("sub") or "").strip()
                if sid:
                    return f"sid:{sid}"
                if sub:
                    return f"user:{sub}"
            except Exception:
                pass
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return f"ip:{forwarded}"
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return f"ip:{host}" if host else "ip:unknown"


def build_limiter() -> Limiter:
    uri = _storage_uri()
    if uri:
        try:
            return Limiter(key_func=_rate_limit_key, storage_uri=uri)
        except Exception as exc:
            logger.warning(
                "SlowAPI Redis storage unavailable (%s) — falling back to in-memory",
                exc,
            )
    return Limiter(key_func=_rate_limit_key)


limiter = build_limiter()
