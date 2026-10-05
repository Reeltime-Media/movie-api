"""Fulfillment uses snapshotted plan duration and refreshes locked intents."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.billing.fulfillment import fulfill_payment_intent


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def first(self):
        return self._value


class _FakeDb:
    def __init__(self):
        self.added = []

    async def execute(self, stmt):
        compiled = str(stmt).lower()
        if "subscription_payments" in compiled:
            return _ScalarResult(None)
        if "users" in compiled:
            return _ScalarResult(SimpleNamespace(id=uuid4()))
        if "subscriptions" in compiled:
            return _ScalarResult(None)
        return _ScalarResult(None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None and obj.__class__.__name__ == "Subscription":
                obj.id = uuid4()


@pytest.mark.asyncio
async def test_fulfill_sub_uses_snapshotted_interval_days(monkeypatch):
    plan = SimpleNamespace(
        code="premium_5m",
        is_active=True,
        billing_interval_days=150,
        price_usd=Decimal("10.99"),
    )

    async def fake_resolve(db, intent):
        return plan

    monkeypatch.setattr(
        "app.billing.fulfillment._resolve_plan_for_subscription_intent",
        fake_resolve,
    )

    async def fake_notify(db, intent, bank=None):
        pass

    monkeypatch.setattr(
        "app.billing.fulfillment.notify_payment_succeeded",
        fake_notify,
    )

    intent = SimpleNamespace(
        status="pending",
        kind="sub",
        user_id=uuid4(),
        intent_id=f"bkg-{uuid4().hex}",
        order_id=f"sub-premium_5m-{uuid4().hex}",
        amount_usd=Decimal("10.99"),
        plan_code="premium_5m",
        plan_interval_days=90,  # snapshotted at checkout — not live plan's 150
        content_id=None,
        series_id=None,
        guest_id=None,
        resolved_at=None,
    )
    db = _FakeDb()
    before = datetime.now(UTC)
    await fulfill_payment_intent(db, intent, bank="bakong")

    subs = [o for o in db.added if o.__class__.__name__ == "Subscription"]
    assert len(subs) == 1
    expected_end = before + timedelta(days=90)
    assert abs((subs[0].current_period_end - expected_end).total_seconds()) < 5


@pytest.mark.asyncio
async def test_lock_intent_requests_populate_existing():
    from app.billing.fulfillment import _lock_intent_if_orm
    from app.models.payment_intent import PaymentIntent

    intent = PaymentIntent(
        intent_id=f"bkg-{uuid4().hex}",
        order_id=f"order-{uuid4().hex}",
        method="bakong",
        kind="single",
        amount_usd=Decimal("2.50"),
        status="pending",
    )
    captured = {}

    class _Db:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return _ScalarResult(intent)

    await _lock_intent_if_orm(_Db(), intent)
    opts = captured["stmt"].get_execution_options()
    assert opts.get("populate_existing") is True
