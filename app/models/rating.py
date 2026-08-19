import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, PrimaryKeyConstraint, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "content_id"),
        CheckConstraint("value BETWEEN 1 AND 5", name="ck_ratings_value_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
