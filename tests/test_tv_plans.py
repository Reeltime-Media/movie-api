"""TV packages: plan audience, top-ups that extend a TV ID, and expired IDs signing in."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.billing import subscription_plans
from app.billing.fulfillment import fulfill_payment_intent
from app.schemas.subscription_plan import (
    SubscriptionPlanCreate,
    SubscriptionPlanRead,
    SubscriptionPlanUpdate,
)
from app.services import tv_access_codes


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect())).lower()


class _Result:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def first(self):
        return self._value

    def all(self):
        return [] if self._value is None else [self._value]


class _RecordingDb:
    """Returns the queued results in order and remembers every statement."""

    def __init__(self, *results):
        self._results = list(results)
        self.statements = []
        self.added = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(self._results.pop(0) if self._results else None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if obj.__class__.__name__ == "Subscription" and getattr(obj, "id", None) is None:
                obj.id = uuid4()

    async def commit(self):
        return None


# ---- plan audience ---------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_can_be_narrowed_to_one_audience():
    db = _RecordingDb()
    await subscription_plans.list_subscription_plans(db, active_only=True, audience="tv")
    sql = _sql(db.statements[0])
    assert "subscription_plans.audience =" in sql
    assert "is_active" in sql


@pytest.mark.asyncio
async def test_admin_listing_without_audience_returns_every_plan():
    db = _RecordingDb()
    await subscription_plans.list_subscription_plans(db, app=None)
    assert "where" not in _sql(db.statements[0])


@pytest.mark.asyncio
async def test_default_plan_is_never_a_tv_plan():
    db = _RecordingDb(SimpleNamespace(code="basic_2w"))
    await subscription_plans.resolve_active_plan(db)
    sql = _sql(db.statements[0])
    assert "subscription_plans.audience =" in sql


def test_plan_schemas_know_the_audience():
    assert SubscriptionPlanCreate(code="x", name="X", price_usd=Decimal("1.00")).audience == "app"
    assert SubscriptionPlanCreate(code="x", name="X", price_usd=Decimal("1.00")).bonus_days == 0
    # A 14-month TV package (425 days) is allowed; a plan longer than two years is not.
    assert (
        SubscriptionPlanCreate(
            code="x", name="X", price_usd=Decimal("1.00"), billing_interval_days=425
        ).billing_interval_days
        == 425
    )
    with pytest.raises(ValidationError):
        SubscriptionPlanCreate(
            code="x", name="X", price_usd=Decimal("1.00"), billing_interval_days=731
        )
    with pytest.raises(ValidationError):
        SubscriptionPlanCreate(code="x", name="X", price_usd=Decimal("1.00"), bonus_days=-1)
    assert (
        SubscriptionPlanCreate(
            code="tv_x", name="X", price_usd=Decimal("1.00"), audience="tv"
        ).audience
        == "tv"
    )
    with pytest.raises(ValidationError):
        SubscriptionPlanCreate(code="x", name="X", price_usd=Decimal("1.00"), audience="web")
    assert SubscriptionPlanUpdate().model_dump(exclude_unset=True) == {}
    read = SubscriptionPlanRead(
        id=uuid4(),
        code="tv_3m",
        name="TV 3 Months",
        description=None,
        price_usd=Decimal("6.99"),
        billing_interval_days=90,
        is_active=True,
        sort_order=10,
        audience="tv",
        bonus_days=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert read.model_dump()["audience"] == "tv"


# ---- paying for a TV package -----------------------------------------------


def _sub_intent(plan_code: str, amount: str):
    return SimpleNamespace(
        status="pending",
        kind="sub",
        user_id=uuid4(),
        intent_id=f"bkg-{uuid4().hex}",
        order_id=f"sub-{plan_code}-{uuid4().hex}",
        amount_usd=Decimal(amount),
        content_id=None,
        series_id=None,
        guest_id=None,
        resolved_at=None,
    )


async def _fulfill(monkeypatch, plan, existing_sub):
    async def fake_resolve(db, intent):
        return plan

    async def fake_notify(db, intent, bank=None):
        return None

    monkeypatch.setattr(
        "app.billing.fulfillment._resolve_plan_for_subscription_intent", fake_resolve
    )
    monkeypatch.setattr("app.billing.fulfillment.notify_payment_succeeded", fake_notify)

    intent = _sub_intent(plan.code, str(plan.price_usd))
    # 1st execute: SubscriptionPayment lookup (none), 2nd: user lock, 3rd: subscription row.
    db = _RecordingDb(None, None, existing_sub)
    await fulfill_payment_intent(db, intent, bank="bakong")
    return db


@pytest.mark.asyncio
async def test_tv_top_up_extends_from_the_current_end_and_moves_the_tv_id(monkeypatch):
    now = datetime.now(UTC)
    current_end = now + timedelta(days=20)
    subscription = SimpleNamespace(
        id=uuid4(),
        plan="tv_access",
        status="active",
        current_period_start=now - timedelta(days=10),
        current_period_end=current_end,
    )
    plan = SimpleNamespace(
        code="tv_6m",
        app="reeltime",
        is_active=True,
        billing_interval_days=180,
        price_usd=Decimal("12.99"),
    )

    db = await _fulfill(monkeypatch, plan, subscription)

    # 20 days left + 6 months and 1 free month (210 days): paying early never wastes
    # the remaining time, and the free month is real extra access.
    assert subscription.current_period_end == current_end + timedelta(days=210)
    assert subscription.plan == "tv_6m"
    assert subscription.status == "active"

    tv_updates = [stmt for stmt in db.statements if _sql(stmt).startswith("update tv_access_codes")]
    assert len(tv_updates) == 1, "the TV ID expiry must follow the top-up"
    sql = _sql(tv_updates[0])
    # Only ever moves the expiry forward.
    assert "tv_access_codes.expires_at <" in sql


@pytest.mark.asyncio
async def test_tv_top_up_after_expiry_starts_from_now(monkeypatch):
    now = datetime.now(UTC)
    subscription = SimpleNamespace(
        id=uuid4(),
        plan="tv_3m",
        status="active",
        current_period_start=now - timedelta(days=100),
        current_period_end=now - timedelta(days=5),
    )
    plan = SimpleNamespace(
        code="tv_12m",
        app="reeltime",
        is_active=True,
        billing_interval_days=365,
        price_usd=Decimal("22.99"),
    )

    await _fulfill(monkeypatch, plan, subscription)

    expected = now + timedelta(days=425)
    assert abs(subscription.current_period_end - expected) < timedelta(minutes=1)


# ---- signing in with an expired TV ID --------------------------------------


@pytest.mark.asyncio
async def test_expired_tv_id_can_still_sign_in_to_top_up(monkeypatch):
    user_id = uuid4()
    row = SimpleNamespace(
        code="TV-ABCD1234",
        is_active=True,
        user_id=user_id,
        expires_at=datetime.now(UTC) - timedelta(days=3),
    )
    user = SimpleNamespace(id=user_id, role="user", is_active=True)

    async def fake_session(db, uid, agent):
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(tv_access_codes, "create_session", fake_session)
    db = _RecordingDb(row, user)

    token = await tv_access_codes.login_with_tv_access_code(db, "tv-abcd1234", "REELTIME TV")

    assert isinstance(token, str) and token
    # The sync of the subscription end matches on the user, so a paid plan (renamed away
    # from "tv_access") is kept in step too.
    sync = _sql(db.statements[2])
    assert sync.startswith("update subscriptions")
    assert "subscriptions.plan" not in sync.split("where", 1)[1]
    # A TV ID is a Reeltime pass: signing in never reactivates a TV5 subscription.
    assert "subscriptions.app =" in sync.split("where", 1)[1]


@pytest.mark.asyncio
async def test_inactive_tv_id_is_still_refused():
    row = SimpleNamespace(
        code="TV-OFF00000",
        is_active=False,
        user_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db = _RecordingDb(row)
    with pytest.raises(Exception) as err:
        await tv_access_codes.login_with_tv_access_code(db, "TV-OFF00000", None)
    assert "inactive" in str(err.value).lower() or "invalid" in str(err.value).lower()


@pytest.mark.asyncio
async def test_tv5_payment_never_moves_the_reeltime_tv_id(monkeypatch):
    now = datetime.now(UTC)
    subscription = SimpleNamespace(
        id=uuid4(),
        plan="tv5_monthly",
        status="active",
        current_period_start=now - timedelta(days=10),
        current_period_end=now + timedelta(days=5),
    )
    plan = SimpleNamespace(
        code="tv5_monthly",
        app="tv5",
        is_active=True,
        billing_interval_days=30,
        price_usd=Decimal("2.99"),
    )

    db = await _fulfill(monkeypatch, plan, subscription)

    assert not [s for s in db.statements if _sql(s).startswith("update tv_access_codes")]
    sub_lookup = [s for s in db.statements if _sql(s).startswith("select subscriptions")]
    assert sub_lookup and "subscriptions.app =" in _sql(sub_lookup[0])
