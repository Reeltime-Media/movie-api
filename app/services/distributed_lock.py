"""Single-owner locks shared across Uvicorn workers (Redis) with flock fallback.

Used by Bakong sweeper / health monitor so only one process runs each loop.
"""

from __future__ import annotations

import fcntl
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_redis_sync: Any | None = None
_redis_failed = False
_local = Lock()


def _sync_redis():
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
        logger.warning("distributed_lock: Redis unavailable (%s) — flock fallback", exc)
        return None


@dataclass
class HeldLock:
    name: str
    token: str
    ttl_seconds: int
    backend: str  # "redis" | "flock"
    _file: Any | None = field(default=None, repr=False)

    def refresh(self) -> bool:
        if self.backend == "redis":
            client = _sync_redis()
            if client is None:
                return False
            try:
                # Only extend if we still own the key.
                current = client.get(self.name)
                if current != self.token:
                    return False
                client.expire(self.name, self.ttl_seconds)
                return True
            except Exception as exc:
                logger.warning("distributed_lock refresh failed name=%s: %s", self.name, exc)
                return False
        return True  # flock held for process life

    def release(self) -> None:
        if self.backend == "redis":
            client = _sync_redis()
            if client is None:
                return
            try:
                # Release only if token matches (Lua-less compare-and-del).
                if client.get(self.name) == self.token:
                    client.delete(self.name)
            except Exception as exc:
                logger.warning("distributed_lock release failed name=%s: %s", self.name, exc)
            return
        if self._file is not None:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None


def try_acquire(
    name: str,
    *,
    ttl_seconds: int = 180,
    flock_path: str | None = None,
) -> HeldLock | None:
    """Try to become the single owner. Returns HeldLock or None if already taken."""
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    ttl = max(30, int(ttl_seconds))
    client = _sync_redis()
    if client is not None:
        try:
            ok = client.set(name, token, nx=True, ex=ttl)
            if ok:
                return HeldLock(name=name, token=token, ttl_seconds=ttl, backend="redis")
            return None
        except Exception as exc:
            logger.warning("distributed_lock Redis acquire failed (%s) — trying flock", exc)

    path = Path(flock_path or f"/tmp/reeltime-{name.replace(':', '-')}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(path, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    return HeldLock(
        name=name,
        token=token,
        ttl_seconds=ttl,
        backend="flock",
        _file=lock_file,
    )


def reset_for_tests() -> None:
    """Drop cached Redis client (tests)."""
    global _redis_sync, _redis_failed
    with _local:
        _redis_sync = None
        _redis_failed = False
