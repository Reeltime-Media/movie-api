"""Free-today membership grants access without purchase or subscription."""

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

    async def execute(self, _stmt):
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


def test_listed_movie_is_accessible_without_purchase(monkeypatch):
    async def listed(_db, _content_id):
        return True

    monkeypatch.setattr(free_today, "is_free_today", listed)
    # No queued results: access must be granted before any purchase lookup.
    allowed = asyncio.run(
        content_access.user_can_access_content(FakeDb([]), make_user(), make_paid_movie())
    )
    assert allowed is True


def test_unlisted_paid_movie_still_requires_purchase(monkeypatch):
    async def not_listed(_db, _content_id):
        return False

    monkeypatch.setattr(free_today, "is_free_today", not_listed)
    # Two queued empty results: the subscription check, then the purchase
    # lookup, both come after the free-today hook.
    allowed = asyncio.run(
        content_access.user_can_access_content(
            FakeDb([FakeResult(scalar=None), FakeResult(scalar=None)]),
            make_user(),
            make_paid_movie(),
        )
    )
    assert allowed is False


def test_subscribed_user_can_access_paid_movie(monkeypatch):
    async def not_listed(_db, _content_id):
        return False

    monkeypatch.setattr(free_today, "is_free_today", not_listed)
    # One queued result: the subscription check finds an active subscription,
    # so access is granted before any purchase lookup runs.
    allowed = asyncio.run(
        content_access.user_can_access_content(
            FakeDb([FakeResult(scalar=object())]), make_user(), make_paid_movie()
        )
    )
    assert allowed is True
