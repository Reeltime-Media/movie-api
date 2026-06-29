from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promotion_banner import PromotionBanner


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
