"""Shared asyncpg / SQLAlchemy settings for Supabase pooler connections."""

from __future__ import annotations

import asyncio
import logging
import ssl
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


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


def asyncpg_connect_args(database_url: str) -> dict:
    """
    Supabase pooler (PgBouncer) + asyncpg:
    - Disable prepared statement caches (required on pooler ports).
    - Use explicit TLS for remote hosts (avoids handshake resets with uvloop).
    """
    args: dict = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "timeout": 60,
        "command_timeout": 60,
    }
    host = _database_host(database_url)
    if host not in ("", "localhost", "127.0.0.1"):
        args["ssl"] = _remote_ssl_context()
    return args


def sqlalchemy_engine_kwargs(database_url: str, *, debug: bool = False) -> dict:
    """Engine options tuned for Supabase session pooler from Docker / uvicorn."""
    return {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_timeout": 30,
        "echo": debug,
        "connect_args": asyncpg_connect_args(database_url),
    }


async def verify_database_connection(
    engine: AsyncEngine,
    *,
    attempts: int = 3,
    base_delay_seconds: float = 2.0,
) -> None:
    """Ping the database with retries (helps during cold Supabase / Docker startup)."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                delay = base_delay_seconds * attempt
                logger.warning(
                    "Database connection attempt %s/%s failed (%s); retrying in %ss",
                    attempt,
                    attempts,
                    exc.__class__.__name__,
                    delay,
                )
                await asyncio.sleep(delay)
    assert last_error is not None
    raise last_error
