"""Podcasts are free or included with any active subscription plan."""

import asyncio
import uuid
from decimal import Decimal

from app.models.content import Content
from app.models.user import User
from app.services import content_access


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


def make_podcast(*, is_free: bool = False) -> Content:
    return Content(
        id=uuid.uuid4(),
        type="podcast",
        title="Horror Hour",
        slug="horror-hour",
        is_published=True,
        is_free=is_free,
        price_usd=Decimal("0"),
    )


def make_user() -> User:
    return User(id=uuid.uuid4(), role="user")


def test_free_podcast_accessible_without_subscription():
    allowed = asyncio.run(
        content_access.can_access_content(FakeDb([]), make_user(), None, make_podcast(is_free=True))
    )
    assert allowed is True


def test_free_podcast_accessible_anonymously():
    allowed = asyncio.run(
        content_access.can_access_content(FakeDb([]), None, None, make_podcast(is_free=True))
    )
    assert allowed is True


def test_plan_podcast_denied_without_user():
    allowed = asyncio.run(
        content_access.can_access_content(FakeDb([]), None, None, make_podcast(is_free=False))
    )
    assert allowed is False


def test_plan_podcast_denied_without_subscription():
    allowed = asyncio.run(
        content_access.can_access_content(
            FakeDb([FakeResult(scalar=None)]),
            make_user(),
            None,
            make_podcast(is_free=False),
        )
    )
    assert allowed is False


def test_plan_podcast_allowed_with_active_subscription():
    allowed = asyncio.run(
        content_access.can_access_content(
            FakeDb([FakeResult(scalar=object())]),
            make_user(),
            None,
            make_podcast(is_free=False),
        )
    )
    assert allowed is True
