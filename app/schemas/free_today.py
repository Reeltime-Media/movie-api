from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

FREE_TODAY_MAX = 10


class FreeTodayItemCreate(BaseModel):
    content_id: UUID
    sort_order: int = 0


class FreeTodayItemUpdate(BaseModel):
    sort_order: int


class FreeTodayItemRead(BaseModel):
    id: UUID
    content_id: UUID
    sort_order: int
    created_at: datetime
    updated_at: datetime
    content_title: str | None = None
    content_slug: str | None = None
    poster_key: str | None = None

    model_config = {"from_attributes": True}
