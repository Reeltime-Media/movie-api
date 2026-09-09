from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.telegram import (
    claim_bakong_daily_limit_alert,
    is_bakong_daily_limit_error,
    notify_bakong_daily_limit,
)


def test_is_bakong_daily_limit_error():
    assert is_bakong_daily_limit_error(17) is True
    assert is_bakong_daily_limit_error("17") is True
    assert is_bakong_daily_limit_error(1) is False
    assert is_bakong_daily_limit_error(None) is False


def test_claim_bakong_daily_limit_alert_once_per_day(tmp_path: Path):
    path = tmp_path / "alert"
    assert claim_bakong_daily_limit_alert(day="2026-09-09", path=path) is True
    assert claim_bakong_daily_limit_alert(day="2026-09-09", path=path) is False
    assert claim_bakong_daily_limit_alert(day="2026-09-10", path=path) is True


@pytest.mark.asyncio
async def test_notify_bakong_daily_limit_sends_once(tmp_path: Path, monkeypatch):
    path = tmp_path / "alert"
    monkeypatch.setattr("app.services.telegram._DAILY_LIMIT_ALERT_PATH", path)
    monkeypatch.setattr("app.services.telegram._ict_today", lambda: "2026-09-09")
    with patch(
        "app.services.telegram.send_telegram_message",
        new_callable=AsyncMock,
    ) as send:
        await notify_bakong_daily_limit()
        await notify_bakong_daily_limit()
        send.assert_awaited_once()
        text = send.await_args.args[0]
        assert "100/day" in text
        assert "ICT midnight" in text
