"""Shared asyncpg / SQLAlchemy settings for Supabase pooler connections."""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Awaitable, Callable
from typing import TypeVar
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
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


def _database_host(database_url: str) -> str:
    # Normalise sqlalchemy URL for urlparse (needs a scheme with //)
    normalised = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return (urlparse(normalised).hostname or "").lower()


def _database_port(database_url: str) -> int | None:
    normalised = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    port = urlparse(normalised).port
    return port


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


def _remote_ssl_context() -> ssl.SSLContext:
    """
    TLS for Supabase pooler from Docker.

    Encryption is required, but the pooler cert chain often fails verification in
    python:3.12-slim (self-signed in chain). CERT_NONE still encrypts traffic.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def is_transient_db_error(exc: BaseException) -> bool:
    """True for timeouts and connection drops that may succeed on retry."""
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, OSError, ConnectionError)):
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
            delay = base_delay_seconds * attempt
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


def asyncpg_connect_args(database_url: str) -> dict:
    """
    Supabase pooler (PgBouncer) + asyncpg:
    - Disable prepared statement caches (required on pooler ports).
    - Use explicit TLS for remote hosts (avoids handshake resets with uvloop).
    """
    args: dict = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "timeout": DEFAULT_CONNECT_TIMEOUT,
        "command_timeout": DEFAULT_COMMAND_TIMEOUT,
    }
    host = _database_host(database_url)
    if host not in ("", "localhost", "127.0.0.1"):
        args["ssl"] = _remote_ssl_context()
    return args


def sqlalchemy_engine_kwargs(database_url: str, *, debug: bool = False) -> dict:
    """Engine options tuned for Supabase session pooler from Docker / uvicorn."""
    return {
        "pool_size": DEFAULT_POOL_SIZE,
        "max_overflow": DEFAULT_MAX_OVERFLOW,
        "pool_pre_ping": True,
        "pool_recycle": DEFAULT_POOL_RECYCLE,
        "pool_timeout": DEFAULT_POOL_TIMEOUT,
        "echo": debug,
        "connect_args": asyncpg_connect_args(database_url),
    }


async def verify_database_connection(
    engine: AsyncEngine,
    *,
    attempts: int = 5,
    base_delay_seconds: float = 2.0,
) -> None:
    """Ping the database with retries (helps during cold Supabase / Docker startup)."""

    async def ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    await run_with_db_retry(
        ping,
        attempts=attempts,
        base_delay_seconds=base_delay_seconds,
        label="database startup ping",
    )


def transient_db_detail() -> str:
    return (
        "Database is temporarily unreachable. "
        "If using Supabase: confirm the project is not paused, use POOLER_DATABASE_URL "
        "(session mode, port 5432), and retry in a few seconds."
    )
