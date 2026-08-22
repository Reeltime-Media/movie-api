from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TVChannelCreate(BaseModel):
    name: str
    description: str | None = None
    source_url: str = Field(..., description="Origin TV HLS (.m3u8) source URL")
    is_free: bool = True


class TVChannelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source_url: str | None = None
    is_published: bool | None = None
    is_free: bool | None = None
    sort_order: int | None = None


class TVChannelRead(BaseModel):
    """Admin view — includes the source URL and live-service state."""

    id: UUID
    slug: str
    name: str
    description: str | None
    logo_key: str | None
    source_url: str
    hls_playback_url: str | None
    status: str
    status_error: str | None
    is_published: bool
    is_free: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TVChannelPublicRead(BaseModel):
    """Public view — never exposes source_url or hls_playback_url."""

    id: UUID
    slug: str
    name: str
    description: str | None
    logo_key: str | None
    status: str
    is_free: bool

    model_config = {"from_attributes": True}


class TVChannelLogoUploadStart(BaseModel):
    content_type: str = "image/jpeg"


class TVChannelLogoUploadStartRead(BaseModel):
    logo_key: str
    upload_url: str


class TVChannelLogoUploadComplete(BaseModel):
    logo_key: str


class TVChannelAuthorizeRead(BaseModel):
    master_url: str
    expires_in: int
