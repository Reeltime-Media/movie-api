from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


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
    """Former bank-credit / watcher settle payload (endpoint disabled)."""

    md5: str | None = None
    intent_id: str | None = None
    status: str | None = None
    paid: bool | None = None


class BakongPendingIntentRead(BaseModel):
    """Former Cambodia watcher pending QR item (endpoint disabled)."""

    intent_id: str
    md5: str
    prev_md5: str | None = None
    created_at: datetime
    qr_created_at: datetime | None = None


class BakongPendingListRead(BaseModel):
    items: list[BakongPendingIntentRead]


class CatalogPricingRead(BaseModel):
    """Public catalog prices charged by checkout (not marketing-copy only)."""

    series_unlock_usd: Decimal
    min_paid_usd: Decimal
    # True once PAYPAL_CLIENT_ID/SECRET are set: clients show the PayPal button only then.
    paypal_enabled: bool = False


class PaypalIntentCreate(BaseModel):
    """Optional hints for where the buyer lands again after PayPal."""

    # Same-site path to open after payment, e.g. "/watch/my-movie". Validated server-side.
    return_path: str | None = Field(default=None, max_length=300)
    # "web" = the website; "app" = the mobile app (return page shows "back to the app").
    client: Literal["web", "app"] = "web"
    # Web origin the buyer started on; honoured only if it is on the CORS allow-list.
    return_origin: str | None = Field(default=None, max_length=200)
    # "paypal" = PayPal login page; "card" = ask PayPal for its Visa/Mastercard page for
    # buyers without a PayPal account (still paid on paypal.com; PayPal may ignore it).
    funding: Literal["paypal", "card"] = "paypal"


class PaypalIntentRead(BaseModel):
    intent_id: str
    order_id: str
    # Open this URL (full-page redirect on web, in-app browser on mobile) to pay on PayPal.
    approve_url: str
    amount_usd: Decimal
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaypalCaptureRequest(BaseModel):
    # PayPal's order id: the "token" query parameter PayPal adds to the return URL.
    order_id: str = Field(min_length=5, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
