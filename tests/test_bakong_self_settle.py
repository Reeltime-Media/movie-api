"""Tests for Bakong self-settle (admin fulfill + webhook helpers)."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.payments import _bakong_webhook_reports_paid
from app.schemas.payment import BakongWebhookPayload


def test_bakong_webhook_reports_paid_variants():
    assert _bakong_webhook_reports_paid(BakongWebhookPayload(paid=True)) is True
    assert _bakong_webhook_reports_paid(BakongWebhookPayload(status="success")) is True
    assert _bakong_webhook_reports_paid(BakongWebhookPayload(status="PAID")) is True
    assert _bakong_webhook_reports_paid(BakongWebhookPayload(status="pending")) is False
    assert _bakong_webhook_reports_paid(BakongWebhookPayload()) is False


@pytest.mark.asyncio
async def test_admin_fulfill_calls_fulfillment():
    from app.routers.admin.payments import admin_fulfill_payment

    intent = SimpleNamespace(
        intent_id="bkg-1",
        order_id="movie-1",
        status="pending",
        resolved_at=None,
    )
    result = SimpleNamespace(scalar_one_or_none=lambda: intent)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with patch(
        "app.routers.admin.payments.fulfill_payment_intent",
        AsyncMock(),
    ) as fulfill:
        out = await admin_fulfill_payment("bkg-1", db, admin=SimpleNamespace(id="a"))
        fulfill.assert_awaited_once()
        assert out.intent_id == "bkg-1"
        assert out.order_id == "movie-1"
