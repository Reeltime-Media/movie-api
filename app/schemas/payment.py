from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, HttpUrl


class PaymentIntentCreate(BaseModel):
    custom_success_url: HttpUrl | None = None


class PaymentIntentRead(BaseModel):
    intent_id: str
    order_id: str
    user_id: UUID | None
    kind: str
    content_id: UUID | None
    amount_usd: Decimal
    status: str
    checkout_url: str
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}
