from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ContentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    genres: list[str] | None = None
    release_year: int | None = None
    rating: Decimal | None = None
    runtime: str | None = None
    trailer_url: str | None = None
    status: str | None = None
    is_published: bool | None = None
    is_free: bool | None = None
    price_usd: Decimal | None = None
    season_number: int | None = None
    episode_number: int | None = None


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


class SeasonRead(BaseModel):
    season_number: int
    episodes: list[ContentRead]
