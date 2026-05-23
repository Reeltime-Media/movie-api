from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.money import validate_usd_price


class SubscriptionPlanCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    price_usd: Decimal = Field(ge=0)

    @field_validator("price_usd")
    @classmethod
    def check_price_usd(cls, value: Decimal) -> Decimal:
        return validate_usd_price(value)
    billing_interval_days: int = Field(default=30, ge=1, le=365)
    is_active: bool = True
    sort_order: int = 0


class SubscriptionPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    price_usd: Decimal | None = Field(default=None, ge=0)

    @field_validator("price_usd")
    @classmethod
    def check_price_usd(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return validate_usd_price(value)
    billing_interval_days: int | None = Field(default=None, ge=1, le=365)
    is_active: bool | None = None
    sort_order: int | None = None


class SubscriptionPlanRead(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    price_usd: Decimal
    billing_interval_days: int
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
