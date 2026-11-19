import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # 'reeltime' | 'tv5' — see app/core/apps.py.
    app: Mapped[str] = mapped_column(
        Text, nullable=False, default="reeltime", server_default="reeltime"
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    billing_interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Who the plan is sold to: "app" = phone/web (the default list), "tv" = the TV app's
    # own packages. TV plans never appear in the phone/web plan list.
    audience: Mapped[str] = mapped_column(Text, nullable=False, default="app", server_default="app")
    # Promotional extra days already counted inside billing_interval_days (e.g. a
    # 6-month plan that gives 1 month free is 210 days with bonus_days = 30). Payment and
    # renewal only use billing_interval_days; clients show the bonus as "free time".
    bonus_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
