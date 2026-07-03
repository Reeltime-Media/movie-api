from __future__ import annotations

import asyncio
import functools
import logging
import random
import ssl
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Supabase session pooler has limited slots; keep the app pool small.
DEFAULT_POOL_SIZE = 3
DEFAULT_MAX_OVERFLOW = 2
DEFAULT_POOL_TIMEOUT = 30
DEFAULT_POOL_RECYCLE = 180
DEFAULT_CONNECT_TIMEOUT = 30
DEFAULT_COMMAND_TIMEOUT = 60


@functools.lru_cache(maxsize=8)
def _parse_database_url(database_url: str) -> object:
    """Parse and cache database URL."""
    # Normalize for urlparse
    normalised = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return urlparse(normalised)


def _database_host(database_url: str) -> str:
    return (_parse_database_url(database_url).hostname or "").lower()


def _database_port(database_url: str) -> int | None:
    return _parse_database_url(database_url).port


def database_connection_label(database_url: str) -> str:
    host = _database_host(database_url)
    port = _database_port(database_url)
    return f"{host}:{port}" if port else host


def validate_database_url(database_url: str, *, pooler_configured: bool) -> list[str]:
    """Return human-readable warnings for common Supabase misconfigurations."""
    warnings: list[str] = []
    host = _database_host(database_url)
    port = _database_port(database_url)

    if port == 6543:
        warnings.append(
            "DATABASE URL uses port 6543 (transaction pooler). "
            "Use session pooler port 5432 for asyncpg."
        )
    if host.startswith("db.") and host.endswith(".supabase.co") and not pooler_configured:
        warnings.append(
            "DATABASE URL uses direct Supabase host db.*. "
            "Set POOLER_DATABASE_URL for Docker and macOS (IPv4 pooler, port 5432)."
        )
    return warnings


@functools.lru_cache(maxsize=4)
def _remote_ssl_context(root_cert_path: str | None = None) -> ssl.SSLContext:
    """SSL context for remote connections; verifies against root_cert_path when given.

    Without a CA bundle we fall back to unverified TLS, because the Supabase
    pooler presents a certificate signed by a project-specific CA that is not
    in the system trust store.
    """
    if root_cert_path:
        return ssl.create_default_context(cafile=root_cert_path)
    logger.warning(
        "Database TLS certificate verification is disabled. "
        "Set DATABASE_SSL_ROOT_CERT to your Supabase CA bundle to enable it."
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def is_transient_db_error(exc: BaseException) -> bool:
    """True for timeouts and connection drops that may succeed on retry."""
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, OSError, ConnectionError)):
        return True
    if isinstance(exc, SATimeoutError):
        # Pool checkout timed out — expected while the database is unreachable.
        return True
    if isinstance(exc, (OperationalError, DBAPIError)):
        message = str(exc).lower()
        return any(
            token in message
            for token in ("timeout", "timed out", "connection", "cancelled", "closed")
        )
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    return bool(cause and cause is not exc and is_transient_db_error(cause))


async def run_with_db_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.5,
    label: str = "database operation",
) -> T:
    """Retry transient Supabase / pooler connection failures."""
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except BaseException as exc:
            last_error = exc
            if not is_transient_db_error(exc) or attempt >= attempts:
                raise
            delay = base_delay_seconds * attempt + random.uniform(0, base_delay_seconds)
            logger.warning(
                "%s failed (%s); retry %s/%s in %ss",
                label,
                exc.__class__.__name__,
                attempt,
                attempts,
                delay,
            )
            await asyncio.sleep(delay)
    assert last_error is not None
    raise last_error


def asyncpg_connect_args(
    database_url: str,
    *,
    ssl_root_cert: str | None = None,
) -> dict[str, Any]:
    """Generate asyncpg connection args (disable caches, add TLS for remote hosts)."""
    args: dict[str, Any] = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "timeout": DEFAULT_CONNECT_TIMEOUT,
        "command_timeout": DEFAULT_COMMAND_TIMEOUT,
    }
    host = _database_host(database_url)
    if host not in ("", "localhost", "127.0.0.1"):
        args["ssl"] = _remote_ssl_context(ssl_root_cert or None)
    return args


def sqlalchemy_engine_kwargs(
    database_url: str,
    *,
    debug: bool = False,
    ssl_root_cert: str | None = None,
) -> dict[str, Any]:
    """Return SQLAlchemy engine kwargs optimized for Supabase pooler."""
    return {
        "pool_size": DEFAULT_POOL_SIZE,
        "max_overflow": DEFAULT_MAX_OVERFLOW,
        "pool_pre_ping": True,
        "pool_recycle": DEFAULT_POOL_RECYCLE,
        "pool_timeout": DEFAULT_POOL_TIMEOUT,
        "echo": debug,
        "connect_args": asyncpg_connect_args(database_url, ssl_root_cert=ssl_root_cert),
    }


async def verify_database_connection(
    engine: AsyncEngine,
    *,
    attempts: int = 5,
    base_delay_seconds: float = 2.0,
) -> None:
    """Ping database with retries for cold Supabase startup."""

    async def ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    await run_with_db_retry(
        ping,
        attempts=attempts,
        base_delay_seconds=base_delay_seconds,
        label="database startup ping",
    )


_DB_LAYER_MODULE_PREFIXES = ("sqlalchemy", "asyncpg", "app.database", "app.db_connect")


def exception_from_db_layer(exc: BaseException) -> bool:
    """True when the exception's traceback passes through the database stack.

    Used to tell database timeouts apart from other asyncio timeouts, since
    asyncpg can raise bare TimeoutError (== asyncio.TimeoutError on 3.11+).
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        tb = current.__traceback__
        while tb is not None:
            module = tb.tb_frame.f_globals.get("__name__", "")
            if module.startswith(_DB_LAYER_MODULE_PREFIXES):
                return True
            tb = tb.tb_next
        current = current.__cause__ or current.__context__
    return False


class DatabaseWarmup:
    """Single-flight, rate-limited reconnect probe for a database that is down.

    Many requests can arrive while the database is unreachable; only one should
    pay for a reconnect attempt (bounded by timeout_seconds), and failed
    attempts are spaced out by cooldown_seconds so traffic bursts do not stack
    slow connection attempts.
    """

    def __init__(
        self,
        ping: Callable[[], Awaitable[None]],
        *,
        cooldown_seconds: float = 5.0,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._ping = ping
        self._cooldown_seconds = cooldown_seconds
        self._timeout_seconds = timeout_seconds
        self._lock = asyncio.Lock()
        self._next_attempt_at = 0.0

    async def try_connect(self) -> bool:
        """Probe the database once; True when it answered."""
        if self._lock.locked():
            # Another request is already probing; let it report the result.
            return False
        async with self._lock:
            if time.monotonic() < self._next_attempt_at:
                return False
            try:
                await asyncio.wait_for(self._ping(), self._timeout_seconds)
            except Exception:
                self._next_attempt_at = time.monotonic() + self._cooldown_seconds
                return False
            return True


def transient_db_detail() -> str:
    return (
        "Database is temporarily unreachable. "
        "If using Supabase: confirm the project is not paused, use POOLER_DATABASE_URL "
        "(session mode, port 5432), and retry in a few seconds."
    )
