from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

COMING_SOON_MAX = 20


class ComingSoonItemCreate(BaseModel):
    content_id: UUID
    sort_order: int = 0


class ComingSoonItemUpdate(BaseModel):
    sort_order: int


class ComingSoonItemRead(BaseModel):
    id: UUID
    content_id: UUID
    sort_order: int
    created_at: datetime
    updated_at: datetime
    content_title: str | None = None
    content_slug: str | None = None
    poster_key: str | None = None
    is_published: bool | None = None

    model_config = {"from_attributes": True}
