"""Pytest configuration and shared fixtures."""

import asyncio
import os
from collections.abc import Iterator
from typing import Any

_SETTINGS_DEFAULTS: dict[str, Any] = {
    "secret_key": "test-secret-key-thirty-two-characters-min",
    "database_url": "postgresql+asyncpg://user:pass@localhost/db",
    "r2_account_id": "test-account",
    "r2_access_key_id": "test-access-key",
    "r2_secret_access_key": "test-secret-key",
    "r2_bucket_name": "movies",
    "r2_public_url": "https://cdn.example.com",
}

# Seed a valid baseline env before any app import below: app.database builds
# its engine when imported, and CI runs with a bare environment (no .env).
# Real env vars win — setdefault never overrides.
for _key, _value in _SETTINGS_DEFAULTS.items():
    os.environ.setdefault(_key.upper(), str(_value))
os.environ.setdefault("TRANSCODE_API_KEY", "test-transcode-key")

import pytest  # noqa: E402

from app.config import Settings, clear_settings_cache, get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
def settings_factory(monkeypatch: pytest.MonkeyPatch):
    """Build Settings from env overrides without reading .env or the lru_cache."""

    def _factory(**overrides: Any) -> Settings:
        clear_settings_cache()
        for key, value in {**_SETTINGS_DEFAULTS, **overrides}.items():
            env_name = key.upper()
            if value is None:
                monkeypatch.delenv(env_name, raising=False)
            else:
                monkeypatch.setenv(env_name, str(value))
        return Settings(_env_file=None)

    return _factory


@pytest.fixture
def settings(settings_factory) -> Settings:
    """Minimal valid Settings instance for integration-style tests."""
    return settings_factory(debug=True)


@pytest.fixture
def cached_settings(settings_factory, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings loaded through get_settings() after env overrides."""
    instance = settings_factory(debug=True)
    clear_settings_cache()
    monkeypatch.setenv("DEBUG", "true")
    for key, value in _SETTINGS_DEFAULTS.items():
        monkeypatch.setenv(key.upper(), str(value))
    return get_settings()


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = None
    try:
        loop = asyncio.new_event_loop()
        yield loop
    finally:
        if loop:
            loop.close()


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async (deselect with '-m \"not asyncio\"')"
    )
