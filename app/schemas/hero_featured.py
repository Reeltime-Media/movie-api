from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class HeroFeaturedItemCreate(BaseModel):
    content_type: Literal["movie", "series"]
    content_id: UUID
    placement: str = Field(default="home", max_length=32)
    is_active: bool = True
    sort_order: int = 0
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class HeroFeaturedItemUpdate(BaseModel):
    content_type: Literal["movie", "series"] | None = None
    content_id: UUID | None = None
    placement: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    sort_order: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class HeroFeaturedItemRead(BaseModel):
    id: UUID
    content_type: str
    content_id: UUID
    placement: str
    is_active: bool
    sort_order: int
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime
    content_title: str | None = None
    content_slug: str | None = None
    poster_key: str | None = None

    model_config = {"from_attributes": True}


class HeroFeaturedSlideRead(BaseModel):
    id: UUID
    content_type: Literal["movie", "series"]
    title: str
    slug: str
    description: str | None
    genres: list[str]
    release_year: int | None
    rating: Decimal | None
    runtime: str | None
    poster_key: str | None
    banner_key: str | None = None
    watch_href: str
    sort_order: int

    @field_validator("genres", mode="before")
    @classmethod
    def default_genres(cls, value: list[str] | None) -> list[str]:
        return value or []
