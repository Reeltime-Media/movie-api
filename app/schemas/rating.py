import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class RatingUpsert(BaseModel):
    value: int = Field(ge=1, le=5, description="Star rating from 1 to 5")


class RatingRead(BaseModel):
    content_id: uuid.UUID
    value: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RatingWriteResult(BaseModel):
    content_id: uuid.UUID
    value: int
    content_rating: Decimal | None
    rating_count: int
