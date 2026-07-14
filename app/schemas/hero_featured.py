from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

HERO_BANNER_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
HERO_VIDEO_TYPES = {"video/mp4", "video/webm"}


def _normalize_optional_text(value: str | None) -> str | None:
    """Strip surrounding whitespace; coerce blank strings to None."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validate_link_url(value: str | None) -> str | None:
    value = _normalize_optional_text(value)
    if value is None:
        return None
    # "//host" is protocol-relative (off-site), not an internal path.
    is_path = value.startswith("/") and not value.startswith("//")
    is_http = value.startswith(("http://", "https://"))
    if not (is_path or is_http):
        raise ValueError(
            "link_url must be a path starting with / (not //) or an http(s) URL"
        )
    return value


def _validate_youtube_url(value: str | None) -> str | None:
    value = _normalize_optional_text(value)
    if value is not None and not value.startswith(("http://", "https://")):
        raise ValueError("youtube_url must be an http(s) URL")
    return value


class HeroFeaturedItemCreate(BaseModel):
    content_type: Literal["movie", "series", "custom"]
    content_id: UUID | None = None
    placement: str = Field(default="home", max_length=32)
    is_active: bool = True
    sort_order: int = 0
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    # Custom-slide fields (content_type == "custom")
    title: str | None = None
    description: str | None = None
    banner_key: str | None = None
    link_url: str | None = None
    # Promo video (any slide type). Uploaded video_key wins over youtube_url.
    video_key: str | None = None
    youtube_url: str | None = None
    # Catalog slides: false = show just the banner, no trailer autoplay.
    video_enabled: bool = True

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("link_url")
    @classmethod
    def check_link_url(cls, value: str | None) -> str | None:
        return _validate_link_url(value)

    @field_validator("youtube_url")
    @classmethod
    def check_youtube_url(cls, value: str | None) -> str | None:
        return _validate_youtube_url(value)

    @model_validator(mode="after")
    def check_slide_shape(self) -> "HeroFeaturedItemCreate":
        if self.content_type == "custom":
            if self.content_id is not None:
                raise ValueError("custom slides must not reference catalog content")
            if not (self.video_key or self.youtube_url):
                raise ValueError(
                    "custom slides require an uploaded video or a YouTube URL"
                )
        elif self.content_id is None:
            raise ValueError("content_id is required for movie and series slides")
        return self


class HeroFeaturedItemUpdate(BaseModel):
    content_type: Literal["movie", "series", "custom"] | None = None
    content_id: UUID | None = None
    placement: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    sort_order: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    title: str | None = None
    description: str | None = None
    banner_key: str | None = None
    link_url: str | None = None
    video_key: str | None = None
    youtube_url: str | None = None
    video_enabled: bool | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("link_url")
    @classmethod
    def check_link_url(cls, value: str | None) -> str | None:
        return _validate_link_url(value)

    @field_validator("youtube_url")
    @classmethod
    def check_youtube_url(cls, value: str | None) -> str | None:
        return _validate_youtube_url(value)


class HeroFeaturedItemRead(BaseModel):
    id: UUID
    content_type: str
    content_id: UUID | None
    placement: str
    is_active: bool
    sort_order: int
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    description: str | None = None
    banner_key: str | None = None
    link_url: str | None = None
    video_key: str | None = None
    youtube_url: str | None = None
    video_enabled: bool = True
    content_title: str | None = None
    content_slug: str | None = None
    poster_key: str | None = None

    model_config = {"from_attributes": True}


class HeroFeaturedSlideRead(BaseModel):
    id: UUID
    content_type: Literal["movie", "series", "custom"]
    title: str
    slug: str = ""
    description: str | None
    genres: list[str]
    release_year: int | None
    rating: Decimal | None
    runtime: str | None
    poster_key: str | None
    banner_key: str | None = None
    watch_href: str | None = None
    sort_order: int
    # Exactly one of these is set when the slide has a video (video_key wins).
    video_key: str | None = None
    youtube_url: str | None = None

    @field_validator("genres", mode="before")
    @classmethod
    def default_genres(cls, value: list[str] | None) -> list[str]:
        return value or []


class HeroUploadStart(BaseModel):
    kind: Literal["banner", "video"]
    content_type: str

    @model_validator(mode="after")
    def check_content_type(self) -> "HeroUploadStart":
        normalized = self.content_type.strip().lower()
        allowed = HERO_BANNER_TYPES if self.kind == "banner" else HERO_VIDEO_TYPES
        if normalized not in allowed:
            raise ValueError(
                f"content_type must be one of {', '.join(sorted(allowed))}"
            )
        self.content_type = normalized
        return self


class HeroUploadStartRead(BaseModel):
    key: str
    upload_url: str
