from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class SeriesPurchaseRead(BaseModel):
    id: UUID
    user_id: UUID | None
    series_id: UUID
    intent_id: str
    order_id: str
    bank: str | None
    amount_usd: Decimal
    purchased_at: datetime

    model_config = {"from_attributes": True}
