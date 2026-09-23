import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WatchProgressUpdate(BaseModel):
    position_seconds: int = Field(ge=0, le=86_400 * 24)
    completed: bool = False


class WatchProgressSeriesRead(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    title_km: str | None = None
    poster_key: str | None = None
    banner_key: str | None = None

    model_config = {"from_attributes": True}


class WatchProgressContentRead(BaseModel):
    id: uuid.UUID
    type: str
    slug: str
    title: str
    title_km: str | None = None
    poster_key: str | None = None
    banner_key: str | None = None
    duration_seconds: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    series: WatchProgressSeriesRead | None = None

    model_config = {"from_attributes": True}


class WatchProgressRead(BaseModel):
    user_id: uuid.UUID
    content_id: uuid.UUID
    position_seconds: int
    completed: bool
    last_watched_at: datetime
    content: WatchProgressContentRead | None = None

    model_config = {"from_attributes": True}
