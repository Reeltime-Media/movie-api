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
    from app.services.bakong_check_cache import STATUS_PAID, STATUS_UNPAID

    intent = _intent(bakong_md5="new", bakong_prev_md5="old")

    async def probe(md5: str) -> str:
        return STATUS_PAID if md5 == "old" else STATUS_UNPAID

    with (
        patch("app.services.bakong_settle.nbc_settle_enabled", return_value=True),
        patch("app.services.bakong_settle.bakong.probe_khqr_status", side_effect=probe),
        patch("app.services.bakong_settle.bakong.check_khqr_paid", AsyncMock(return_value=True)),
    ):
        assert await bakong_md5s_paid(intent) is True


@pytest.mark.asyncio
async def test_bakong_md5s_paid_disabled_without_nbc():
    intent = _intent()
    with patch("app.services.bakong_settle.nbc_settle_enabled", return_value=False):
        assert await bakong_md5s_paid(intent) is False


@pytest.mark.asyncio
async def test_bakong_md5s_paid_skips_prev_when_unknown():
    from app.services.bakong_check_cache import STATUS_UNKNOWN

    intent = _intent(bakong_md5="new", bakong_prev_md5="old")
    with (
        patch("app.services.bakong_settle.nbc_settle_enabled", return_value=True),
        patch(
            "app.services.bakong_settle.bakong.probe_khqr_status",
            AsyncMock(return_value=STATUS_UNKNOWN),
        ) as probe,
    ):
        assert await bakong_md5s_paid(intent) is False
        assert probe.await_count == 1


@pytest.mark.asyncio
async def test_settle_bakong_intent_if_paid_fulfills():
    intent = _intent()
    db = AsyncMock()

    with (
        patch("app.services.bakong_settle.nbc_settle_enabled", return_value=True),
        patch("app.services.bakong_settle.bakong_md5s_paid", AsyncMock(return_value=True)),
        patch(
            "app.services.bakong_settle.fulfill_payment_intent",
            AsyncMock(),
        ) as fulfill,
    ):
        assert await settle_bakong_intent_if_paid(db, intent) is True
        fulfill.assert_awaited_once()


@pytest.mark.asyncio
async def test_settle_noop_when_nbc_disabled():
    intent = _intent()
    db = AsyncMock()
    with (
        patch("app.services.bakong_settle.nbc_settle_enabled", return_value=False),
        patch(
            "app.services.bakong_settle.fulfill_payment_intent",
            AsyncMock(),
        ) as fulfill,
    ):
        assert await settle_bakong_intent_if_paid(db, intent) is False
        fulfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_bakong_qr_confirmed_unpaid_false_when_unknown():
    from app.services.bakong_check_cache import STATUS_UNKNOWN
    from app.services.bakong_settle import bakong_qr_confirmed_unpaid

    intent = _intent()
    with (
        patch("app.services.bakong_settle.nbc_settle_enabled", return_value=True),
        patch(
            "app.services.bakong_settle.bakong.probe_khqr_status",
            AsyncMock(return_value=STATUS_UNKNOWN),
        ),
    ):
        assert await bakong_qr_confirmed_unpaid(intent) is False


@pytest.mark.asyncio
async def test_bakong_qr_confirmed_unpaid_true_when_unpaid():
    from app.services.bakong_check_cache import STATUS_UNPAID
    from app.services.bakong_settle import bakong_qr_confirmed_unpaid

    intent = _intent()
    with (
        patch("app.services.bakong_settle.nbc_settle_enabled", return_value=True),
        patch(
            "app.services.bakong_settle.bakong.probe_khqr_status",
            AsyncMock(return_value=STATUS_UNPAID),
        ),
    ):
        assert await bakong_qr_confirmed_unpaid(intent) is True


@pytest.mark.asyncio
async def test_bakong_qr_confirmed_unpaid_true_without_nbc():
    from app.services.bakong_settle import bakong_qr_confirmed_unpaid

    intent = _intent()
    with patch("app.services.bakong_settle.nbc_settle_enabled", return_value=False):
        assert await bakong_qr_confirmed_unpaid(intent) is True


@pytest.mark.asyncio
async def test_bakong_qr_confirmed_unpaid_false_when_prev_paid():
    from app.services.bakong_check_cache import STATUS_PAID, STATUS_UNPAID
    from app.services.bakong_settle import bakong_qr_confirmed_unpaid

    intent = _intent(bakong_md5="new", bakong_prev_md5="old")

    async def probe(md5: str) -> str:
        return STATUS_PAID if md5 == "old" else STATUS_UNPAID

    with (
        patch("app.services.bakong_settle.nbc_settle_enabled", return_value=True),
        patch("app.services.bakong_settle.bakong.probe_khqr_status", side_effect=probe),
    ):
        assert await bakong_qr_confirmed_unpaid(intent) is False


@pytest.mark.asyncio
async def test_settle_skips_when_unpaid():
    intent = _intent()
    db = AsyncMock()

    with (
        patch("app.services.bakong_settle.nbc_settle_enabled", return_value=True),
        patch("app.services.bakong_settle.bakong_md5s_paid", AsyncMock(return_value=False)),
        patch(
            "app.services.bakong_settle.fulfill_payment_intent",
            AsyncMock(),
        ) as fulfill,
    ):
        assert await settle_bakong_intent_if_paid(db, intent) is False
        fulfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_settle_pending_movie_bakong_for_buyer():
    from uuid import uuid4

    from app.services.bakong_settle import settle_pending_movie_bakong_for_buyer

    content_id = uuid4()
    user_id = uuid4()
    intent = _intent(content_id=content_id, user_id=user_id, guest_id=None)
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [intent]))
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    with (
        patch("app.services.bakong_settle.nbc_settle_enabled", return_value=True),
        patch("app.services.bakong_quota.bakong_checks_blocked", return_value=False),
        patch(
            "app.services.bakong_settle.settle_bakong_intent_if_paid",
            AsyncMock(return_value=True),
        ) as settle,
    ):
        assert (
            await settle_pending_movie_bakong_for_buyer(
                db, content_id=content_id, user_id=user_id, guest_id=None
            )
            is True
        )
        settle.assert_awaited_once()


@pytest.mark.asyncio
async def test_settle_pending_movie_skipped_without_nbc():
    from uuid import uuid4

    from app.services.bakong_settle import settle_pending_movie_bakong_for_buyer

    db = AsyncMock()
    with patch("app.services.bakong_settle.nbc_settle_enabled", return_value=False):
        assert (
            await settle_pending_movie_bakong_for_buyer(
                db, content_id=uuid4(), user_id=uuid4(), guest_id=None
            )
            is False
        )
    db.execute.assert_not_awaited()
