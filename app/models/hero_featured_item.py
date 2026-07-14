import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HeroFeaturedItem(Base):
    __tablename__ = "hero_featured_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Custom-slide fields (used when content_type == "custom")
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    banner_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Promo video (any slide type). Uploaded video_key wins over youtube_url.
    video_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Catalog slides: false = show just the banner, no trailer autoplay.
    video_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    placement: Mapped[str] = mapped_column(Text, nullable=False, default="home")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
