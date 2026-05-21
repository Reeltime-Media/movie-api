from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


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
