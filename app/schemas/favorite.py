import uuid
from datetime import datetime

from pydantic import BaseModel


class FavoriteRead(BaseModel):
    content_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
