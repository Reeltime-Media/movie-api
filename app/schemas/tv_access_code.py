from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _normalize_code(value: str) -> str:
    cleaned = "".join(ch for ch in value.strip().upper() if ch.isalnum() or ch in "-_")
    if len(cleaned) < 4:
        raise ValueError("TV ID must be at least 4 characters")
    if len(cleaned) > 32:
        raise ValueError("TV ID must be at most 32 characters")
    return cleaned


class TvAccessCodeCreate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    expires_at: datetime
    code: str | None = Field(
        default=None,
        description="Optional custom TV ID. Auto-generated when omitted.",
    )
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_optional_code(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return _normalize_code(value)

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TvAccessCodeUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    expires_at: datetime | None = None
    is_active: bool | None = None

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TvAccessCodeRead(BaseModel):
    id: UUID
    code: str
    label: str | None
    user_id: UUID
    expires_at: datetime
    is_active: bool
    created_at: datetime
    updated_at: datetime
    is_expired: bool

    model_config = {"from_attributes": True}


class TvAccessLoginRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return _normalize_code(value)
