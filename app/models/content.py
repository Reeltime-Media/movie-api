import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_STATUS = {"draft", "review", "scheduled", "published"}


class Content(Base):
    __tablename__ = "content"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)  # 'single' | 'episode'
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=True,
    )
    season_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    genres: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    release_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    runtime: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    poster_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    banner_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    trailer_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    hls_master_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # 'draft' | 'review' | 'scheduled' | 'published'
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transcode_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
