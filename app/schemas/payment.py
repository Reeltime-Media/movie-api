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
    method: str
    kind: str
    content_id: UUID | None
    amount_usd: Decimal
    status: str
    # Baray only — redirect target. Bakong intents poll in place, no redirect.
    checkout_url: str | None = None
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class BakongPaymentIntentRead(BaseModel):
    intent_id: str
    order_id: str
    qr_string: str
    amount_usd: Decimal
    status: str
    created_at: datetime
    # Merchant / receiver name on the KHQR card (matches QR payload).
    merchant_name: str = ""

    model_config = {"from_attributes": True}
