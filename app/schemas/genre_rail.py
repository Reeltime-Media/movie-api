from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.content import ContentListItemRead

GENRE_RAIL_MAX_PER_GENRE = 12


class GenreRailItemCreate(BaseModel):
    genre_name: str = Field(min_length=1, max_length=80)
    content_id: UUID
    sort_order: int = 0


class GenreRailItemUpdate(BaseModel):
    sort_order: int


class GenreRailItemRead(BaseModel):
    id: UUID
    genre_name: str
    content_id: UUID
    sort_order: int
    created_at: datetime
    updated_at: datetime
    content_title: str | None = None
    content_slug: str | None = None
    poster_key: str | None = None

    model_config = {"from_attributes": True}


class GenreRailRead(BaseModel):
    """One home-page genre rail with movies in admin order."""

    genre: str
    movies: list[ContentListItemRead]
