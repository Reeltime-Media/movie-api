from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.money import validate_usd_price
from app.schemas.upload import MultipartPart, MultipartPartUrl, MultipartUploadAbort


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class SeriesUpdate(BaseModel):
    title: str | None = None
    title_km: str | None = None
    description: str | None = None
    genres: list[str] | None = None
    release_year: int | None = None
    rating: Decimal | None = None
    monthly_price_usd: Decimal | None = None
    is_published: bool | None = None
    trailer_url: str | None = None
    poster_key: str | None = None  # set after uploading poster via /poster/start
    banner_key: str | None = None  # set after uploading banner via /banner/start

    @field_validator("title_km")
    @classmethod
    def normalize_title_km(cls, value: str | None) -> str | None:
        return _empty_to_none(value)

    @field_validator("monthly_price_usd")
    @classmethod
    def check_monthly_price_usd(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return validate_usd_price(value)


class SeriesRead(BaseModel):
    id: UUID
    slug: str
    title: str
    title_km: str | None = None
    description: str | None
    genres: list[str]
    release_year: int | None
    rating: Decimal | None
    poster_key: str | None
    banner_key: str | None
    trailer_url: str | None
    monthly_price_usd: Decimal
    is_published: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SeriesListItemRead(BaseModel):
    id: UUID
    slug: str
    title: str
    title_km: str | None = None
    genres: list[str]
    release_year: int | None
    rating: Decimal | None
    poster_key: str | None
    banner_key: str | None
    monthly_price_usd: Decimal

    model_config = {"from_attributes": True}


class CreateSeriesBody(BaseModel):
    title: str
    title_km: str | None = None
    monthly_price_usd: Decimal
    description: str | None = None
    genres: list[str] = []
    release_year: int | None = None
    rating: Decimal | None = None
    trailer_url: str | None = None

    @field_validator("title_km")
    @classmethod
    def normalize_title_km(cls, value: str | None) -> str | None:
        return _empty_to_none(value)

    @field_validator("monthly_price_usd")
    @classmethod
    def check_monthly_price_usd(cls, value: Decimal) -> Decimal:
        return validate_usd_price(value)


class SeriesPosterStart(BaseModel):
    poster_content_type: str = "image/jpeg"


class SeriesPosterStartRead(BaseModel):
    series_id: UUID
    poster_key: str
    poster_upload_url: str


class SeriesBannerStart(BaseModel):
    banner_content_type: str = "image/jpeg"


class SeriesBannerStartRead(BaseModel):
    series_id: UUID
    banner_key: str
    banner_upload_url: str


class EpisodeUploadStart(BaseModel):
    season_number: int
    episode_number: int
    file_size_bytes: int = Field(gt=0, description="Raw video file size — used to presign all part URLs")
    video_content_type: str = "video/mp4"
    poster_content_type: str | None = None


class EpisodeUploadStartRead(BaseModel):
    content_id: UUID
    episode_slug: str
    upload_id: str
    source_key: str
    part_size: int
    part_count: int
    part_urls: list[MultipartPartUrl]
    poster_key: str | None = None
    poster_upload_url: str | None = None


class EpisodeUploadComplete(BaseModel):
    content_id: UUID
    episode_slug: str
    source_key: str
    upload_id: str
    parts: list[MultipartPart]
    title: str
    season_number: int
    episode_number: int
    description: str | None = None
    runtime: str | None = None
    status: str = "draft"
    is_free: bool = False
    trailer_url: str | None = None
    poster_key: str | None = None


class EpisodeUploadAbort(MultipartUploadAbort):
    pass


class EpisodeAssetUploadStart(BaseModel):
    """Replace video and/or poster on an existing episode (admin edit)."""

    video_content_type: str | None = None
    poster_content_type: str | None = None


class EpisodeAssetUploadStartRead(BaseModel):
    source_key: str | None = None
    video_upload_url: str | None = None
    poster_key: str | None = None
    poster_upload_url: str | None = None


class EpisodeAssetUploadComplete(BaseModel):
    source_key: str | None = None
    poster_key: str | None = None
