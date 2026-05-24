"""Shared asyncpg / SQLAlchemy settings for Supabase pooler connections."""

from __future__ import annotations

import ssl
from urllib.parse import urlparse


def _database_host(database_url: str) -> str:
    # Normalise sqlalchemy URL for urlparse (needs a scheme with //)
    normalised = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return (urlparse(normalised).hostname or "").lower()


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
        "timeout": 30,
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
        "echo": debug,
        "connect_args": asyncpg_connect_args(database_url),
    }
