"""Subscription package fulfillment must credit the plan the user paid for."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.payment_fulfillment import (
    _plan_code_from_order_id,
    fulfill_payment_intent,
)


def test_plan_code_from_order_id():
    assert _plan_code_from_order_id("sub-premium_5m-abcdef012345") == "premium_5m"
    assert _plan_code_from_order_id("sub-value_1m-deadbeef") == "value_1m"
    assert _plan_code_from_order_id("sub-abcdef012345") is None
    assert _plan_code_from_order_id("movie-xyz") is None


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
    def __init__(self, *, existing_payment=None, existing_sub=None, plan=None):
        self.existing_payment = existing_payment
        self.existing_sub = existing_sub
        self.plan = plan
        self.added = []
        self.execute_calls = 0

    async def execute(self, _stmt):
        self.execute_calls += 1
        # 1st: SubscriptionPayment lookup, 2nd: Subscription lookup
        if self.execute_calls == 1:
            return _ScalarResult(self.existing_payment)
        return _ScalarResult(self.existing_sub)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None and obj.__class__.__name__ == "Subscription":
                obj.id = uuid4()


@pytest.mark.asyncio
async def test_fulfill_sub_uses_paid_plan_not_default(monkeypatch):
    premium = SimpleNamespace(
        code="premium_5m",
        is_active=True,
        billing_interval_days=150,
        price_usd=Decimal("10.99"),
    )
    basic = SimpleNamespace(
        code="basic_2w",
        is_active=True,
        billing_interval_days=14,
        price_usd=Decimal("3.49"),
    )

    async def fake_resolve_plan(db, intent):
        assert "premium_5m" in intent.order_id
        return premium

    monkeypatch.setattr(
        "app.services.payment_fulfillment._resolve_plan_for_subscription_intent",
        fake_resolve_plan,
    )
    notified = {}

    async def fake_notify(db, intent, bank=None):
        notified["ok"] = True

    monkeypatch.setattr(
        "app.services.payment_fulfillment.notify_payment_succeeded",
        fake_notify,
    )

    intent = SimpleNamespace(
        status="pending",
        kind="sub",
        user_id=uuid4(),
        intent_id=f"bkg-{uuid4().hex}",
        order_id=f"sub-premium_5m-{uuid4().hex}",
        amount_usd=Decimal("10.99"),
        content_id=None,
        series_id=None,
        guest_id=None,
        resolved_at=None,
    )
    db = _FakeDb()

    await fulfill_payment_intent(db, intent, bank="bakong")

    assert intent.status == "succeeded"
    sub = next(o for o in db.added if o.__class__.__name__ == "Subscription" or hasattr(o, "plan"))
    # Newly constructed Subscription in fulfillment uses the model class —
    # our fake just stores whatever was passed to add().
    plans = [getattr(o, "plan", None) for o in db.added]
    assert "premium_5m" in plans
    assert basic.code not in plans
    assert notified.get("ok") is True
