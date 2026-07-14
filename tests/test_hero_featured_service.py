"""Slide resolution and validation for hero featured items."""

import asyncio
import uuid

import pytest

from app.models.content import Content
from app.models.hero_featured_item import HeroFeaturedItem
from app.services.hero_featured import _build_slide, validate_hero_content


def make_custom_item(**overrides) -> HeroFeaturedItem:
    defaults = dict(
        id=uuid.uuid4(),
        content_type="custom",
        content_id=None,
        placement="home",
        is_active=True,
        sort_order=0,
        title="Summer promo",
        description="Big sale",
        banner_key="hero/banners/x.jpg",
        link_url="https://example.com",
        video_key=None,
        youtube_url=None,
    )
    defaults.update(overrides)
    return HeroFeaturedItem(**defaults)


def test_custom_slide_builds_from_own_fields():
    item = make_custom_item()
    slide = _build_slide(item, {}, {})
    assert slide is not None
    assert slide.content_type == "custom"
    assert slide.title == "Summer promo"
    assert slide.description == "Big sale"
    assert slide.banner_key == "hero/banners/x.jpg"
    assert slide.watch_href == "https://example.com"
    assert slide.slug == ""
    assert slide.genres == []


def test_custom_slide_without_link_has_null_watch_href():
    item = make_custom_item(link_url=None)
    slide = _build_slide(item, {}, {})
    assert slide is not None
    assert slide.watch_href is None


def test_uploaded_video_wins_over_youtube():
    item = make_custom_item(
        video_key="hero/videos/x.mp4",
        youtube_url="https://youtu.be/abc",
    )
    slide = _build_slide(item, {}, {})
    assert slide is not None
    assert slide.video_key == "hero/videos/x.mp4"
    assert slide.youtube_url is None


def test_youtube_used_when_no_uploaded_video():
    item = make_custom_item(youtube_url="https://youtu.be/abc")
    slide = _build_slide(item, {}, {})
    assert slide is not None
    assert slide.video_key is None
    assert slide.youtube_url == "https://youtu.be/abc"


def test_movie_slide_passes_video_fields_through():
    movie_id = uuid.uuid4()
    movie = Content(
        id=movie_id,
        title="Test Movie",
        slug="test-movie",
        description=None,
        genres=["Action"],
        release_year=2026,
        rating=None,
        runtime="2h",
        poster_key=None,
        banner_key=None,
    )
    item = HeroFeaturedItem(
        id=uuid.uuid4(),
        content_type="movie",
        content_id=movie_id,
        placement="home",
        is_active=True,
        sort_order=1,
        youtube_url="https://youtu.be/abc",
    )
    slide = _build_slide(item, {movie_id: movie}, {})
    assert slide is not None
    assert slide.content_type == "movie"
    assert slide.youtube_url == "https://youtu.be/abc"
    assert slide.watch_href == "/watch?slug=test-movie"


def make_movie(movie_id, **overrides) -> Content:
    defaults = dict(
        id=movie_id,
        title="Test Movie",
        slug="test-movie",
        description=None,
        genres=[],
        release_year=2026,
        rating=None,
        runtime="2h",
        poster_key=None,
        banner_key=None,
        trailer_url=None,
    )
    defaults.update(overrides)
    return Content(**defaults)


def make_movie_item(movie_id, **overrides) -> HeroFeaturedItem:
    defaults = dict(
        id=uuid.uuid4(),
        content_type="movie",
        content_id=movie_id,
        placement="home",
        is_active=True,
        sort_order=0,
    )
    defaults.update(overrides)
    return HeroFeaturedItem(**defaults)


def test_movie_slide_falls_back_to_catalog_trailer():
    movie_id = uuid.uuid4()
    movie = make_movie(movie_id, trailer_url="https://youtu.be/trailer")
    item = make_movie_item(movie_id)
    slide = _build_slide(item, {movie_id: movie}, {})
    assert slide is not None
    assert slide.youtube_url == "https://youtu.be/trailer"
    assert slide.video_key is None


def test_movie_explicit_youtube_beats_trailer():
    movie_id = uuid.uuid4()
    movie = make_movie(movie_id, trailer_url="https://youtu.be/trailer")
    item = make_movie_item(movie_id, youtube_url="https://youtu.be/manual")
    slide = _build_slide(item, {movie_id: movie}, {})
    assert slide is not None
    assert slide.youtube_url == "https://youtu.be/manual"


def test_movie_uploaded_video_beats_trailer():
    movie_id = uuid.uuid4()
    movie = make_movie(movie_id, trailer_url="https://youtu.be/trailer")
    item = make_movie_item(movie_id, video_key="hero/videos/x.mp4")
    slide = _build_slide(item, {movie_id: movie}, {})
    assert slide is not None
    assert slide.video_key == "hero/videos/x.mp4"
    assert slide.youtube_url is None


def test_movie_without_trailer_or_video_has_no_video():
    movie_id = uuid.uuid4()
    movie = make_movie(movie_id)
    item = make_movie_item(movie_id)
    slide = _build_slide(item, {movie_id: movie}, {})
    assert slide is not None
    assert slide.video_key is None
    assert slide.youtube_url is None


def test_video_disabled_suppresses_trailer_and_explicit_video():
    movie_id = uuid.uuid4()
    movie = make_movie(movie_id, trailer_url="https://youtu.be/trailer")
    item = make_movie_item(
        movie_id,
        video_key="hero/videos/x.mp4",
        youtube_url="https://youtu.be/manual",
        video_enabled=False,
    )
    slide = _build_slide(item, {movie_id: movie}, {})
    assert slide is not None
    assert slide.video_key is None
    assert slide.youtube_url is None


def test_video_enabled_true_keeps_trailer_fallback():
    movie_id = uuid.uuid4()
    movie = make_movie(movie_id, trailer_url="https://youtu.be/trailer")
    item = make_movie_item(movie_id, video_enabled=True)
    slide = _build_slide(item, {movie_id: movie}, {})
    assert slide is not None
    assert slide.youtube_url == "https://youtu.be/trailer"


def test_validate_custom_requires_video():
    with pytest.raises(ValueError, match="video"):
        asyncio.run(
            validate_hero_content(None, content_type="custom", content_id=None)
        )


def test_validate_custom_rejects_content_id():
    with pytest.raises(ValueError, match="catalog"):
        asyncio.run(
            validate_hero_content(
                None,
                content_type="custom",
                content_id=uuid.uuid4(),
                youtube_url="https://youtu.be/abc",
            )
        )


def test_validate_custom_ok_with_youtube():
    asyncio.run(
        validate_hero_content(
            None,
            content_type="custom",
            content_id=None,
            youtube_url="https://youtu.be/abc",
        )
    )


def test_validate_custom_ok_with_uploaded_video():
    asyncio.run(
        validate_hero_content(
            None,
            content_type="custom",
            content_id=None,
            video_key="hero/videos/x.mp4",
        )
    )


def test_validate_movie_requires_content_id():
    with pytest.raises(ValueError, match="content_id"):
        asyncio.run(
            validate_hero_content(None, content_type="movie", content_id=None)
        )
