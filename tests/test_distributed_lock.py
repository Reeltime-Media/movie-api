"""Distributed lock: Redis NX when available, flock fallback otherwise."""

from unittest.mock import MagicMock

from app.services import distributed_lock


def test_flock_acquire_and_release(tmp_path, monkeypatch):
    distributed_lock.reset_for_tests()
    monkeypatch.setattr(distributed_lock, "_sync_redis", lambda: None)
    path = str(tmp_path / "sweeper.lock")

    first = distributed_lock.try_acquire("bakong:test", ttl_seconds=60, flock_path=path)
    assert first is not None
    assert first.backend == "flock"

    second = distributed_lock.try_acquire("bakong:test", ttl_seconds=60, flock_path=path)
    assert second is None

    first.release()
    third = distributed_lock.try_acquire("bakong:test", ttl_seconds=60, flock_path=path)
    assert third is not None
    third.release()


def test_redis_acquire_uses_set_nx(monkeypatch):
    distributed_lock.reset_for_tests()
    client = MagicMock()
    client.set.return_value = True
    monkeypatch.setattr(distributed_lock, "_sync_redis", lambda: client)

    held = distributed_lock.try_acquire("bakong:sweeper", ttl_seconds=120)
    assert held is not None
    assert held.backend == "redis"
    client.set.assert_called()
    args, kwargs = client.set.call_args
    assert args[0] == "bakong:sweeper"
    assert kwargs.get("nx") is True
    assert kwargs.get("ex") == 120

    client.get.return_value = held.token
    assert held.refresh() is True
    held.release()
    client.delete.assert_called_with("bakong:sweeper")


def test_redis_busy_returns_none(monkeypatch):
    distributed_lock.reset_for_tests()
    client = MagicMock()
    client.set.return_value = None
    monkeypatch.setattr(distributed_lock, "_sync_redis", lambda: client)

    assert distributed_lock.try_acquire("bakong:health-monitor") is None
