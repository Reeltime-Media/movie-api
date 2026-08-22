import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TVChannel(Base):
    __tablename__ = "tv_channels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Origin TV HLS source (.m3u8) FFmpeg restreams from — admin-only, never
    # exposed to the frontend.
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Live HLS output URL served by the restream service's origin server, set
    # once the live service reports the channel as running.
    hls_playback_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'offline' | 'starting' | 'live' | 'error'
    status: Mapped[str] = mapped_column(Text, nullable=False, default="offline")
    status_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
