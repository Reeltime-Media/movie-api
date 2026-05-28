from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.core.money import validate_usd_price


class SeriesUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    genres: list[str] | None = None
    release_year: int | None = None
    rating: Decimal | None = None
    monthly_price_usd: Decimal | None = None
    is_published: bool | None = None
    trailer_url: str | None = None
    poster_key: str | None = None  # set after uploading poster via /poster/start

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
    description: str | None
    genres: list[str]
    release_year: int | None
    rating: Decimal | None
    poster_key: str | None
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
    genres: list[str]
    release_year: int | None
    rating: Decimal | None
    poster_key: str | None
    monthly_price_usd: Decimal

    model_config = {"from_attributes": True}
