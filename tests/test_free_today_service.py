"""Validation, enrichment, and membership checks for Free movies today."""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from app.models.content import Content
from app.models.free_today_item import FreeTodayItem
from app.services.free_today import (
    enrich_admin_free_today,
    is_free_today,
    validate_free_today_add,
)


class FakeResult:
    def __init__(self, scalar=None, items=None):
        self._scalar = scalar
        self._items = items or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._items


class FakeDb:
    """Returns queued results in order, one per execute() call."""

    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        return self._results.pop(0)


def test_add_rejects_missing_movie():
    db = FakeDb([FakeResult(scalar=None)])
    with pytest.raises(ValueError, match="Movie not found"):
        asyncio.run(validate_free_today_add(db, uuid.uuid4()))


def test_add_rejects_duplicate():
    movie_id = uuid.uuid4()
    db = FakeDb([FakeResult(scalar=movie_id), FakeResult(scalar=uuid.uuid4())])
    with pytest.raises(ValueError, match="already"):
        asyncio.run(validate_free_today_add(db, movie_id))


def test_add_rejects_eleventh_pick():
    movie_id = uuid.uuid4()
    db = FakeDb(
        [FakeResult(scalar=movie_id), FakeResult(scalar=None), FakeResult(scalar=10)]
    )
    with pytest.raises(ValueError, match="limited to 10"):
        asyncio.run(validate_free_today_add(db, movie_id))


def test_add_allows_tenth_pick():
    movie_id = uuid.uuid4()
    db = FakeDb(
        [FakeResult(scalar=movie_id), FakeResult(scalar=None), FakeResult(scalar=9)]
    )
    asyncio.run(validate_free_today_add(db, movie_id))


def test_is_free_today_true_and_false():
    content_id = uuid.uuid4()
    assert asyncio.run(is_free_today(FakeDb([FakeResult(scalar=uuid.uuid4())]), content_id))
    assert not asyncio.run(is_free_today(FakeDb([FakeResult(scalar=None)]), content_id))


def test_enrich_sets_movie_fields():
    movie_id = uuid.uuid4()
    movie = Content(id=movie_id, title="Test Movie", slug="test-movie", poster_key="p.webp")
    item = FreeTodayItem(id=uuid.uuid4(), content_id=movie_id, sort_order=1)
    item.created_at = item.updated_at = datetime.now(timezone.utc)
    db = FakeDb([FakeResult(items=[movie])])
    enriched = asyncio.run(enrich_admin_free_today(db, [item]))
    assert enriched[0].content_title == "Test Movie"
    assert enriched[0].content_slug == "test-movie"
    assert enriched[0].poster_key == "p.webp"


def test_enrich_empty_list_short_circuits():
    assert asyncio.run(enrich_admin_free_today(FakeDb([]), [])) == []
