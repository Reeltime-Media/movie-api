"""Async L2 (Redis) path for catalog response cache."""

import json
from unittest.mock import AsyncMock

import pytest

from app.services.response_cache import (
    _CACHE,
    cache_get_async,
    cache_get_or_set,
    cache_set_async,
)


@pytest.fixture(autouse=True)
def _clear_l1():
    _CACHE.clear()
    yield
    _CACHE.clear()


@pytest.mark.asyncio
async def test_cache_get_async_reads_redis_on_l1_miss(monkeypatch):
    payload = {"items": [1, 2], "total": 2}
    monkeypatch.setattr(
        "app.services.shared_cache.cache_get_bytes",
        AsyncMock(return_value=json.dumps(payload).encode()),
    )
    assert await cache_get_async("movies:p1") == payload
    # L1 populated for next hit without Redis.
    monkeypatch.setattr(
        "app.services.shared_cache.cache_get_bytes",
        AsyncMock(side_effect=AssertionError("should not hit Redis")),
    )
    assert await cache_get_async("movies:p1") == payload


@pytest.mark.asyncio
async def test_cache_set_async_writes_redis(monkeypatch):
    sets: list[tuple[str, bytes, float]] = []

    async def fake_set(key: str, value: bytes, ttl_seconds: float) -> None:
        sets.append((key, value, ttl_seconds))

    monkeypatch.setattr("app.services.shared_cache.cache_set_bytes", fake_set)
    await cache_set_async("hero:home", [{"id": "1"}], ttl_seconds=30)
    assert len(sets) == 1
    assert sets[0][0] == "catalog:hero:home"
    assert json.loads(sets[0][1]) == [{"id": "1"}]


@pytest.mark.asyncio
async def test_cache_get_or_set_uses_redis_before_factory(monkeypatch):
    monkeypatch.setattr(
        "app.services.shared_cache.cache_get_bytes",
        AsyncMock(return_value=json.dumps(["from-redis"]).encode()),
    )
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        return ["from-db"]

    result = await cache_get_or_set("genres", factory)
    assert result == ["from-redis"]
    assert calls == 0
