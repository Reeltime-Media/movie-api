from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promotion_banner import PromotionBanner


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def reorder_promotion_banners(db: AsyncSession, ids: list[UUID]) -> set[str]:
    """Apply a banner order, or nothing if any id is wrong. Returns the placements touched."""
    result = await db.execute(select(PromotionBanner).where(PromotionBanner.id.in_(ids)))
    by_id = {banner.id: banner for banner in result.scalars().all()}
    if len(ids) != len(set(ids)) or set(ids) != set(by_id):
        raise ValueError("These banners changed. Refresh and try again.")
    for index, banner_id in enumerate(ids):
        by_id[banner_id].sort_order = index
    return {banner.placement for banner in by_id.values()}


async def list_active_promotion_banners(
    db: AsyncSession,
    *,
    placement: str = "home",
) -> list[PromotionBanner]:
    now = _utc_now()
    stmt = (
        select(PromotionBanner)
        .where(
            PromotionBanner.placement == placement,
            PromotionBanner.is_active.is_(True),
            or_(PromotionBanner.starts_at.is_(None), PromotionBanner.starts_at <= now),
            or_(PromotionBanner.ends_at.is_(None), PromotionBanner.ends_at >= now),
        )
        .order_by(PromotionBanner.sort_order.asc(), PromotionBanner.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
