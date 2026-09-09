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
    series_id: UUID | None = None
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


class BakongWebhookPayload(BaseModel):
    """External Bakong paid notification (self-hosted watcher / future bank hook)."""

    md5: str | None = None
    intent_id: str | None = None
    status: str | None = None
    paid: bool | None = None


class BakongPendingIntentRead(BaseModel):
    """Open Bakong QR for the Cambodia watcher to check via NBC."""

    intent_id: str
    md5: str
    prev_md5: str | None = None
    created_at: datetime
    qr_created_at: datetime | None = None


class BakongPendingListRead(BaseModel):
    items: list[BakongPendingIntentRead]
