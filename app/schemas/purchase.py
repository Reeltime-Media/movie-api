from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class PurchaseCreate(BaseModel):
    content_id: UUID
    intent_id: str
    order_id: str
    bank: str | None = None
    amount_usd: Decimal


class PurchaseRead(BaseModel):
    id: UUID
    user_id: UUID
    content_id: UUID
    intent_id: str
    order_id: str
    bank: str | None
    amount_usd: Decimal
    purchased_at: datetime
    expires_at: datetime | None
    first_played_at: datetime | None

    model_config = {"from_attributes": True}
