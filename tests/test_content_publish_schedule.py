"""Unit tests for scheduled movie publish state helper."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.content_publish import (
    apply_movie_publish_state,
    promote_scheduled_movie_to_published,
)


def _movie(**kwargs):
    defaults = {
        "id": uuid4(),
        "type": "single",
        "status": "draft",
        "is_published": False,
        "publish_at": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_publish_now_clears_schedule():
    movie = _movie(status="scheduled", publish_at=datetime.now(UTC) + timedelta(hours=1))
    apply_movie_publish_state(movie, status="published")
    assert movie.status == "published"
    assert movie.is_published is True
    assert movie.publish_at is None


def test_schedule_requires_publish_at():
    movie = _movie()
    with pytest.raises(HTTPException) as exc:
        apply_movie_publish_state(movie, status="scheduled", publish_at=None, publish_at_set=True)
    assert exc.value.status_code == 422


def test_schedule_future_keeps_unpublished():
    when = datetime.now(UTC) + timedelta(days=1)
    movie = _movie()
    apply_movie_publish_state(movie, status="scheduled", publish_at=when, publish_at_set=True)
    assert movie.status == "scheduled"
    assert movie.is_published is False
    assert movie.publish_at == when


def test_draft_clears_schedule():
    movie = _movie(
        status="scheduled",
        publish_at=datetime.now(UTC) + timedelta(hours=2),
        is_published=False,
    )
    apply_movie_publish_state(movie, status="draft")
    assert movie.status == "draft"
    assert movie.is_published is False
    assert movie.publish_at is None


def test_promote_helper():
    movie = _movie(
        status="scheduled",
        publish_at=datetime.now(UTC) - timedelta(minutes=1),
        is_published=False,
    )
    promote_scheduled_movie_to_published(movie)
    assert movie.status == "published"
    assert movie.is_published is True
    assert movie.publish_at is None
