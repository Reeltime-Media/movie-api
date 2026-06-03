from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _validate_cta_href(value: str | None) -> str | None:
    if value is None:
        return None
    href = value.strip()
    if not href:
        return None
    if not href.startswith("/") or href.startswith("//"):
        raise ValueError("cta_href must be a site path starting with /")
    if "://" in href or "\\" in href:
        raise ValueError("cta_href must be a relative path")
    return href


class PromotionBannerCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=500)
    image_key: str | None = None
    cta_label: str | None = Field(default=None, max_length=80)
    cta_href: str | None = Field(default=None, max_length=500)
    placement: str = Field(default="home", max_length=32)
    is_active: bool = True
    sort_order: int = 0
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("cta_href")
    @classmethod
    def check_cta_href(cls, value: str | None) -> str | None:
        return _validate_cta_href(value)


class PromotionBannerUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subtitle: str | None = None
    image_key: str | None = None
    cta_label: str | None = Field(default=None, max_length=80)
    cta_href: str | None = Field(default=None, max_length=500)
    placement: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    sort_order: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("cta_href")
    @classmethod
    def check_cta_href(cls, value: str | None) -> str | None:
        return _validate_cta_href(value)


class PromotionBannerRead(BaseModel):
    id: UUID
    title: str
    subtitle: str | None
    image_key: str | None
    cta_label: str | None
    cta_href: str | None
    placement: str
    is_active: bool
    sort_order: int
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromotionBannerImageStart(BaseModel):
    content_type: str

    @field_validator("content_type")
    @classmethod
    def check_content_type(cls, value: str) -> str:
        allowed = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError("content_type must be image/jpeg, image/png, or image/webp")
        return normalized


class PromotionBannerImageStartRead(BaseModel):
    image_key: str
    upload_url: str
