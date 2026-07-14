"""Validation rules for hero featured item schemas."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.hero_featured import (
    HeroFeaturedItemCreate,
    HeroFeaturedSlideRead,
    HeroUploadStart,
)


def test_custom_slide_requires_title():
    with pytest.raises(ValidationError, match="title"):
        HeroFeaturedItemCreate(content_type="custom")


def test_custom_slide_rejects_blank_title():
    with pytest.raises(ValidationError, match="title"):
        HeroFeaturedItemCreate(content_type="custom", title="   ")


def test_custom_slide_rejects_content_id():
    with pytest.raises(ValidationError, match="catalog"):
        HeroFeaturedItemCreate(
            content_type="custom", title="Promo", content_id=uuid.uuid4()
        )


def test_custom_slide_valid_with_optional_fields():
    item = HeroFeaturedItemCreate(
        content_type="custom",
        title="Summer promo",
        link_url="https://example.com",
        youtube_url="https://youtu.be/abc123",
    )
    assert item.content_id is None
    assert item.link_url == "https://example.com"


def test_movie_slide_requires_content_id():
    with pytest.raises(ValidationError, match="content_id"):
        HeroFeaturedItemCreate(content_type="movie")


def test_series_slide_requires_content_id():
    with pytest.raises(ValidationError, match="content_id"):
        HeroFeaturedItemCreate(content_type="series")


def test_custom_title_is_stripped():
    item = HeroFeaturedItemCreate(content_type="custom", title="  Promo  ")
    assert item.title == "Promo"


def test_link_url_rejects_javascript_scheme():
    with pytest.raises(ValidationError):
        HeroFeaturedItemCreate(
            content_type="custom", title="Promo", link_url="javascript:alert(1)"
        )


def test_link_url_accepts_internal_path():
    item = HeroFeaturedItemCreate(
        content_type="custom", title="Promo", link_url="/pricing"
    )
    assert item.link_url == "/pricing"


def test_link_url_rejects_protocol_relative():
    with pytest.raises(ValidationError, match="link_url"):
        HeroFeaturedItemCreate(
            content_type="custom", title="Promo", link_url="//evil.com"
        )


def test_youtube_url_rejects_non_http():
    with pytest.raises(ValidationError):
        HeroFeaturedItemCreate(
            content_type="custom", title="Promo", youtube_url="ftp://x"
        )


def test_movie_slide_accepts_video_fields():
    item = HeroFeaturedItemCreate(
        content_type="movie",
        content_id=uuid.uuid4(),
        video_key="hero/videos/x.mp4",
    )
    assert item.video_key == "hero/videos/x.mp4"


def test_slide_read_allows_null_watch_href_and_custom_type():
    slide = HeroFeaturedSlideRead(
        id=uuid.uuid4(),
        content_type="custom",
        title="Promo",
        slug="",
        description=None,
        genres=None,
        release_year=None,
        rating=None,
        runtime=None,
        poster_key=None,
        banner_key=None,
        watch_href=None,
        sort_order=0,
    )
    assert slide.watch_href is None
    assert slide.video_key is None


def test_upload_start_banner_rejects_video_mime():
    with pytest.raises(ValidationError):
        HeroUploadStart(kind="banner", content_type="video/mp4")


def test_upload_start_video_rejects_image_mime():
    with pytest.raises(ValidationError):
        HeroUploadStart(kind="video", content_type="image/png")


def test_upload_start_normalizes_mime():
    start = HeroUploadStart(kind="video", content_type=" VIDEO/MP4 ")
    assert start.content_type == "video/mp4"
