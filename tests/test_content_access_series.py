"""One-time series unlock works without a subscription package, including guests."""

import asyncio
import uuid

from app.models.content import Content
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


def make_paid_episode(series_id=None) -> Content:
    return Content(
        id=uuid.uuid4(),
        type="episode",
        title="Episode 2",
        slug="ep-2",
        is_published=True,
        is_free=False,
        series_id=series_id or uuid.uuid4(),
        season_number=1,
        episode_number=2,
    )


def test_guest_without_series_purchase_cannot_watch_paid_episode():
    allowed = asyncio.run(
        content_access.can_access_content(
            FakeDb([FakeResult(scalar=None)]),
            None,
            "guest-token",
            make_paid_episode(),
        )
    )
    assert allowed is False


def test_guest_with_series_purchase_can_watch_paid_episode_without_package():
    allowed = asyncio.run(
        content_access.can_access_content(
            FakeDb([FakeResult(scalar=object())]),
            None,
            "guest-token",
            make_paid_episode(),
        )
    )
    assert allowed is True
