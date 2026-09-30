import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.dialects import postgresql

from app.routers.watch_progress import _history_row, list_watch_progress


def _content(**changes):
    return SimpleNamespace(
        **(
            {
                "id": uuid.uuid4(),
                "type": "single",
                "slug": "older-title",
                "title": "Older title",
                "title_km": "រឿង",
                "poster_key": "poster.webp",
                "banner_key": None,
                "duration_seconds": 3600,
                "season_number": None,
                "episode_number": None,
                "is_published": True,
                "hls_master_key": "private/master.m3u8",
            }
            | changes
        )
    )


def _progress(content):
    return SimpleNamespace(
        user_id=uuid.uuid4(),
        content_id=content.id,
        position_seconds=120,
        completed=False,
        last_watched_at=datetime.now(UTC),
    )


def test_movie_history_contains_resume_metadata_without_stream_secrets():
    content = _content()
    result = _history_row(_progress(content), content, None).model_dump(mode="json")
    assert result["position_seconds"] == 120
    assert result["content"]["slug"] == "older-title"
    assert result["content"]["duration_seconds"] == 3600
    assert result["content"]["title_km"] == "រឿង"
    assert "hls_master_key" not in result["content"]


def test_episode_history_links_to_parent_series_and_exact_episode():
    content = _content(type="episode", season_number=2, episode_number=4)
    series = SimpleNamespace(id=uuid.uuid4(), slug="the-show", title="The show", is_published=True)
    row = _history_row(_progress(content), content, series)
    assert row.content.series.slug == "the-show"
    assert row.content.season_number == 2
    assert row.content.episode_number == 4


def test_unpublished_titles_and_series_withhold_metadata_but_keep_progress():
    for content, series in [
        (_content(is_published=False), None),
        (_content(type="episode"), None),
        (_content(type="episode"), SimpleNamespace(is_published=False)),
    ]:
        row = _history_row(_progress(content), content, series)
        assert row.content is None
        assert row.position_seconds == 120


def test_history_fetches_metadata_in_one_query_scoped_to_current_user():
    content = _content()
    progress = _progress(content)
    user = SimpleNamespace(id=progress.user_id)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(progress, content, None)]))
    )
    rows = asyncio.run(list_watch_progress(db, user))
    assert rows[0].content.id == content.id
    db.execute.assert_awaited_once()
    query = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert user.id in query.params.values()
    assert "watch_progress.user_id =" in str(query)
    assert "ORDER BY watch_progress.last_watched_at DESC" in str(query)
    assert "JOIN content" in str(query)
    assert "JOIN series" in str(query)
