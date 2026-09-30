"""Bakong NBC circuit shares state via Redis when available."""

import time
from unittest.mock import MagicMock

from app.services import bakong_quota


def test_note_and_blocked_work_in_process_without_redis(monkeypatch):
    monkeypatch.setattr(bakong_quota, "_sync_redis", lambda: None)
    bakong_quota.clear_bakong_rate_limit()
    # clear resets _redis_failed; keep Redis disabled.
    monkeypatch.setattr(bakong_quota, "_sync_redis", lambda: None)

    assert bakong_quota.bakong_checks_blocked() is False
    bakong_quota.note_bakong_rate_limited(cooldown_seconds=120)
    assert bakong_quota.bakong_checks_blocked() is True
    assert bakong_quota.bakong_checks_blocked_remaining_seconds() > 0


def test_blocked_reads_redis_unix_deadline(monkeypatch):
    client = MagicMock()
    client.get.return_value = str(time.time() + 300)
    monkeypatch.setattr(bakong_quota, "_sync_redis", lambda: client)
    with bakong_quota._lock:
        bakong_quota._blocked_until_monotonic = 0.0

    assert bakong_quota.bakong_checks_blocked() is True
    client.get.assert_called_with("bakong:nbc_blocked_until")


def test_note_writes_redis(monkeypatch):
    client = MagicMock()
    client.get.return_value = None
    monkeypatch.setattr(bakong_quota, "_sync_redis", lambda: client)

    bakong_quota.note_bakong_rate_limited(cooldown_seconds=120)
    assert client.set.called
    args, kwargs = client.set.call_args
    assert args[0] == "bakong:nbc_blocked_until"
    assert float(args[1]) > time.time()
