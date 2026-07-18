"""Server-side entitlement checks for catalog and watch progress."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.content import Content
from app.models.purchase import Purchase
from app.models.subscription import Subscription
from app.models.user import User
from app.services import free_today


async def get_published_content_or_404(
    db: AsyncSession,
    content_id: UUID,
    *,
    user: User | None = None,
) -> Content:
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content:
        raise NotFoundError("Content not found")
    if user and user.role == "admin":
        return content
    if not content.is_published:
        raise NotFoundError("Content not found")
    return content


async def user_has_active_subscription(db: AsyncSession, user_id: UUID) -> bool:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
            Subscription.current_period_end > now,
        )
    )
    return result.scalar_one_or_none() is not None


def _movie_is_free(content: Content) -> bool:
    if content.is_free:
        return True
    if content.price_usd is None:
        return True
    return content.price_usd <= Decimal("0")


async def user_can_access_content(db: AsyncSession, user: User, content: Content) -> bool:
    return await can_access_content(db, user, None, content)


async def can_access_content(
    db: AsyncSession,
    user: User | None,
    guest_id: str | None,
    content: Content,
) -> bool:
    """Same entitlement rules as `user_can_access_content`, plus an anonymous
    `guest_id` fallback for single movies (guests never get series/episode
    access — that requires a real subscription)."""
    if user and user.role == "admin":
        return True
    if not content.is_published:
        return False
    if content.is_free:
        return True
    if content.type == "single":
        if _movie_is_free(content):
            return True
        # Admin-curated "Free movies today" picks are free while listed.
        if await free_today.is_free_today(db, content.id):
            return True
        if user:
            purchase = await db.execute(
                select(Purchase).where(
                    Purchase.user_id == user.id,
                    Purchase.content_id == content.id,
                )
            )
            return purchase.scalar_one_or_none() is not None
        if guest_id:
            purchase = await db.execute(
                select(Purchase).where(
                    Purchase.guest_id == guest_id,
                    Purchase.content_id == content.id,
                )
            )
            return purchase.scalar_one_or_none() is not None
        return False
    if content.type == "episode":
        return bool(user) and await user_has_active_subscription(db, user.id)
    return False


async def assert_can_track_watch_progress(
    db: AsyncSession,
    user: User,
    content_id: UUID,
) -> Content:
    content = await get_published_content_or_404(db, content_id, user=user)
    if not await user_can_access_content(db, user, content):
        raise ForbiddenError("You do not have access to this title")
    return content
