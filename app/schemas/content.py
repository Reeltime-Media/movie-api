from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.money import validate_usd_price


class ContentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    genres: list[str] | None = None
    release_year: int | None = None
    rating: Decimal | None = None
    runtime: str | None = None
    runtime_minutes: int | None = Field(default=None, gt=0)
    trailer_url: str | None = None
    status: str | None = None
    is_published: bool | None = None
    is_free: bool | None = None
    price_usd: Decimal | None = None
    season_number: int | None = None
    episode_number: int | None = None

    @field_validator("price_usd")
    @classmethod
    def check_price_usd(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return validate_usd_price(value)


class ContentRead(BaseModel):
    id: UUID
    type: str
    slug: str
    title: str
    description: str | None
    series_id: UUID | None
    season_number: int | None
    episode_number: int | None
    genres: list[str]
    release_year: int | None
    rating: Decimal | None
    runtime: str | None
    duration_seconds: int | None
    poster_key: str | None
    trailer_url: str | None
    hls_master_key: str | None
    price_usd: Decimal | None
    status: str
    is_published: bool
    is_free: bool
    transcode_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContentListItemRead(BaseModel):
    id: UUID
    type: str
    slug: str
    title: str
    poster_key: str | None
    price_usd: Decimal | None
    rating: Decimal | None
    runtime: str | None
    release_year: int | None
    is_free: bool

    model_config = {"from_attributes": True}


class AdminContentRead(ContentRead):
    """Admin catalog row — includes unique viewer count from watch_progress."""

    watch_count: int = 0


class SeasonRead(BaseModel):
    season_number: int
    episodes: list[ContentRead]
