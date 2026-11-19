import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MatchDetails(Base):
    """Fight card for a TV5 Kun Khmer match; the video itself is its Content row."""

    __tablename__ = "match_details"

    content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("content.id", ondelete="CASCADE"),
        primary_key=True,
    )
    red_fighter: Mapped[str] = mapped_column(Text, nullable=False)
    blue_fighter: Mapped[str] = mapped_column(Text, nullable=False)
    event_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    winner: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
