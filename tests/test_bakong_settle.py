"""Unit tests for Bakong QR TTL / settle helpers."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.bakong_settle import bakong_md5s_paid, qr_is_stale, settle_bakong_intent_if_paid


def _intent(**overrides):
    base = {
        "method": "bakong",
        "status": "pending",
        "bakong_md5": "current-md5",
        "bakong_prev_md5": None,
        "bakong_qr_created_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
        "amount_usd": Decimal("2.99"),
        "intent_id": "bkg-test",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestQrIsStale:
    def test_fresh_qr_not_stale(self, settings_factory):
        settings_factory(debug=True, bakong_qr_ttl_minutes=10)
        intent = _intent(
            bakong_qr_created_at=datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        assert qr_is_stale(intent) is False

    def test_old_qr_is_stale(self, settings_factory):
        settings_factory(debug=True, bakong_qr_ttl_minutes=10)
        intent = _intent(
            bakong_qr_created_at=datetime.now(timezone.utc) - timedelta(minutes=11)
        )
        assert qr_is_stale(intent) is True

    def test_falls_back_to_created_at(self, settings_factory):
        settings_factory(debug=True, bakong_qr_ttl_minutes=10)
        intent = _intent(
            bakong_qr_created_at=None,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=12),
        )
        assert qr_is_stale(intent) is True


@pytest.mark.asyncio
async def test_bakong_md5s_paid_checks_previous():
    intent = _intent(bakong_md5="new", bakong_prev_md5="old")

    async def check(md5: str) -> bool:
        return md5 == "old"

    with patch("app.services.bakong_settle.bakong.check_khqr_paid", side_effect=check):
        assert await bakong_md5s_paid(intent) is True


@pytest.mark.asyncio
async def test_settle_bakong_intent_if_paid_fulfills():
    intent = _intent()
    db = AsyncMock()

    with (
        patch("app.services.bakong_settle.bakong_md5s_paid", AsyncMock(return_value=True)),
        patch(
            "app.services.bakong_settle.fulfill_payment_intent",
            AsyncMock(),
        ) as fulfill,
    ):
        assert await settle_bakong_intent_if_paid(db, intent) is True
        fulfill.assert_awaited_once()


@pytest.mark.asyncio
async def test_settle_skips_when_unpaid():
    intent = _intent()
    db = AsyncMock()

    with (
        patch("app.services.bakong_settle.bakong_md5s_paid", AsyncMock(return_value=False)),
        patch(
            "app.services.bakong_settle.fulfill_payment_intent",
            AsyncMock(),
        ) as fulfill,
    ):
        assert await settle_bakong_intent_if_paid(db, intent) is False
        fulfill.assert_not_awaited()
