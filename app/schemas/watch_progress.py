import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WatchProgressUpdate(BaseModel):
    position_seconds: int = Field(ge=0, le=86_400 * 24)
    completed: bool = False


class WatchProgressRead(BaseModel):
    user_id: uuid.UUID
    content_id: uuid.UUID
    position_seconds: int
    completed: bool
    last_watched_at: datetime

    model_config = {"from_attributes": True}
