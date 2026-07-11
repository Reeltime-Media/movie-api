from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class SubscriptionCreate(BaseModel):
    plan: str = "series_monthly"


class SubscriptionRead(BaseModel):
    id: UUID
    user_id: UUID
    plan: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubscriptionPaymentRead(BaseModel):
    id: UUID
    subscription_id: UUID
    intent_id: str
    order_id: str
    bank: str | None
    amount_usd: Decimal
    paid_at: datetime
    period_extended_to: datetime

    model_config = {"from_attributes": True}
