from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, model_validator


class ContentCreate(BaseModel):
    type: Literal["single", "episode"]
    slug: str
    title: str
    description: str | None = None
    series_id: UUID | None = None
    season_number: int | None = None
    episode_number: int | None = None
    price_usd: Decimal | None = None

    @model_validator(mode="after")
    def check_type_constraints(self):
        if self.type == "single":
            if self.price_usd is None:
                raise ValueError("price_usd is required for single content")
            if self.series_id is not None:
                raise ValueError("series_id must be null for single content")
        else:
            if self.series_id is None:
                raise ValueError("series_id is required for episode content")
            if self.price_usd is not None:
                raise ValueError("price_usd must be null for episode content")
        return self


class ContentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    is_published: bool | None = None
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
    duration_seconds: int | None
    poster_key: str | None
    hls_master_key: str | None
    price_usd: Decimal | None
    transcode_status: str
    is_published: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PresignedUploadResponse(BaseModel):
    upload_url: str
    key: str
