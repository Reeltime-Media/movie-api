import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.core.money import validate_usd_price


class MultipartPartUrl(BaseModel):
    part_number: int
    url: str


class PartUrlRead(BaseModel):
    url: str


class MultipartPart(BaseModel):
    part_number: int
    etag: str


class MultipartUploadAbort(BaseModel):
    source_key: str
    upload_id: str


class MovieUploadStart(BaseModel):
    title: str
    file_size_bytes: int = Field(gt=0, description="Raw video file size — used to presign all part URLs")
    video_content_type: str = "video/mp4"
    poster_content_type: str | None = None
    banner_content_type: str | None = None


class MovieUploadStartRead(BaseModel):
    content_id: uuid.UUID
    slug: str
    upload_id: str
    source_key: str
    part_size: int
    part_count: int
    part_urls: list[MultipartPartUrl]
    poster_key: str | None = None
    poster_upload_url: str | None = None
    banner_key: str | None = None
    banner_upload_url: str | None = None


class MovieUploadComplete(BaseModel):
    content_id: uuid.UUID
    slug: str
    source_key: str
    upload_id: str
    parts: list[MultipartPart]
    title: str
    title_km: str | None = None
    price_usd: Decimal
    description: str | None = None
    genres: list[str] = []
    release_year: int | None = None
    rating: Decimal | None = None
    runtime_minutes: int | None = Field(default=None, gt=0)
    status: str = "draft"
    trailer_url: str | None = None
    poster_key: str | None = None
    banner_key: str | None = None

    @field_validator("title_km")
    @classmethod
    def normalize_title_km(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("price_usd")
    @classmethod
    def check_price_usd(cls, value: Decimal) -> Decimal:
        return validate_usd_price(value)
