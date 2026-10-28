import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TelegramBotLogin(Base):
    """Phone sign-in through the bot: the app opens t.me/<bot>?start=<code>.

    pending → started (user tapped Start; identity recorded) → confirmed
    (user tapped Confirm) → used (app polled and got a token).
    """

    __tablename__ = "telegram_bot_logins"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # SHA-256 hex digest — the raw code only exists in the app and the t.me link.
    code_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    telegram_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
