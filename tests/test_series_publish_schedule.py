"""Unit tests for scheduled series publish state helper."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.series_publish import (
    apply_series_publish_state,
    promote_scheduled_series_to_published,
)


def _series(**kwargs):
    defaults = {
        "id": uuid4(),
        "status": "draft",
        "is_published": False,
        "publish_at": None,
        "poster_key": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_publish_now_clears_schedule():
    series = _series(status="scheduled", publish_at=datetime.now(UTC) + timedelta(hours=1))
    apply_series_publish_state(series, status="published")
    assert series.status == "published"
    assert series.is_published is True
    assert series.publish_at is None


def test_schedule_requires_publish_at():
    series = _series()
    with pytest.raises(HTTPException) as exc:
        apply_series_publish_state(series, status="scheduled", publish_at=None, publish_at_set=True)
    assert exc.value.status_code == 422


def test_schedule_future_keeps_unpublished():
    when = datetime.now(UTC) + timedelta(days=1)
    series = _series()
    apply_series_publish_state(series, status="scheduled", publish_at=when, publish_at_set=True)
    assert series.status == "scheduled"
    assert series.is_published is False
    assert series.publish_at == when


def test_draft_clears_schedule():
    series = _series(
        status="scheduled",
        publish_at=datetime.now(UTC) + timedelta(hours=2),
        is_published=False,
    )
    apply_series_publish_state(series, status="draft")
    assert series.status == "draft"
    assert series.is_published is False
    assert series.publish_at is None


def test_promote_helper():
    series = _series(
        status="scheduled",
        publish_at=datetime.now(UTC) - timedelta(minutes=1),
        is_published=False,
    )
    promote_scheduled_series_to_published(series)
    assert series.status == "published"
    assert series.is_published is True
    assert series.publish_at is None
