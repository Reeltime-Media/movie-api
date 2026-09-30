"""Precomputed is_free_today must skip a second FreeTodayItem lookup."""

import asyncio
import uuid
from decimal import Decimal

from app.models.content import Content
from app.models.user import User
from app.services import content_access, free_today


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class FakeDb:
    def __init__(self, results):
        self._results = list(results)
        self.execute_count = 0

    async def execute(self, _stmt):
        self.execute_count += 1
        return self._results.pop(0)


def make_paid_movie() -> Content:
    return Content(
        id=uuid.uuid4(),
        type="single",
        title="Paid Movie",
        slug="paid-movie",
        is_published=True,
        is_free=False,
        price_usd=Decimal("4.99"),
    )


def make_user() -> User:
    return User(id=uuid.uuid4(), role="user")


def test_precomputed_true_skips_free_today_lookup(monkeypatch):
    calls = 0

    async def boom(_db, _content_id):
        nonlocal calls
        calls += 1
        raise AssertionError("is_free_today must not be called when precomputed")

    monkeypatch.setattr(free_today, "is_free_today", boom)
    allowed = asyncio.run(
        content_access.can_access_content(
            FakeDb([]),
            make_user(),
            None,
            make_paid_movie(),
            is_free_today=True,
        )
    )
    assert allowed is True
    assert calls == 0


def test_precomputed_false_skips_lookup_and_continues(monkeypatch):
    calls = 0

    async def boom(_db, _content_id):
        nonlocal calls
        calls += 1
        raise AssertionError("is_free_today must not be called when precomputed")

    monkeypatch.setattr(free_today, "is_free_today", boom)
    db = FakeDb([FakeResult(scalar=object())])  # active subscription
    allowed = asyncio.run(
        content_access.can_access_content(
            db,
            make_user(),
            None,
            make_paid_movie(),
            is_free_today=False,
        )
    )
    assert allowed is True
    assert calls == 0
    assert db.execute_count == 1
