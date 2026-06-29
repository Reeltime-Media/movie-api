from datetime import datetime
import uuid

from pydantic import BaseModel, field_validator


class GenreCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Genre name cannot be empty")
        return v


class GenreRead(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}
