from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class SeriesCreate(BaseModel):
    slug: str
    title: str
    description: str | None = None
    monthly_price_usd: Decimal


class SeriesUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    monthly_price_usd: Decimal | None = None
    is_published: bool | None = None


class SeriesRead(BaseModel):
    id: UUID
    slug: str
    title: str
    description: str | None
    poster_key: str | None
    monthly_price_usd: Decimal
    is_published: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
