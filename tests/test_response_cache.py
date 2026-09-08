"""Tiny in-process TTL cache used to avoid re-querying Postgres on every
catalog list request."""

import pytest

from app.services.response_cache import (
    CATALOG_TTL_SECONDS,
    _CACHE,
    cache_get,
    cache_get_or_set,
    cache_set,
)


def test_get_returns_none_for_missing_key():
    assert cache_get("nope") is None


def test_set_then_get_returns_the_value():
    cache_set("movies:page=1", {"items": [1, 2, 3]}, ttl_seconds=30, now=100.0)
    assert cache_get("movies:page=1", now=100.0) == {"items": [1, 2, 3]}


def test_get_returns_none_once_ttl_has_elapsed():
    cache_set("movies:page=1", "value", ttl_seconds=30, now=100.0)
    assert cache_get("movies:page=1", now=129.999) == "value"
    assert cache_get("movies:page=1", now=130.0) is None


def test_expired_entry_is_evicted_not_just_ignored():
    cache_set("k", "value", ttl_seconds=10, now=0.0)
    assert cache_get("k", now=10.0) is None
    assert "k" not in _CACHE


def test_different_keys_do_not_collide():
    cache_set("movies:page=1", "page one", ttl_seconds=30, now=0.0)
    cache_set("movies:page=2", "page two", ttl_seconds=30, now=0.0)
    assert cache_get("movies:page=1", now=0.0) == "page one"
    assert cache_get("movies:page=2", now=0.0) == "page two"


def test_catalog_ttl_is_thirty_seconds():
    assert CATALOG_TTL_SECONDS == 30


@pytest.mark.asyncio
async def test_cache_get_or_set_skips_factory_on_hit():
    _CACHE.clear()
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        return ["hero"]

    first = await cache_get_or_set("hero:home", factory)
    second = await cache_get_or_set("hero:home", factory)
    assert first == second == ["hero"]
    assert calls == 1
