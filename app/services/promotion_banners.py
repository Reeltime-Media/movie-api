from datetime import datetime, timezone

from sqlalchemy import select
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
        )
        .order_by(PromotionBanner.sort_order.asc(), PromotionBanner.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    active: list[PromotionBanner] = []
    for row in rows:
        if row.starts_at and row.starts_at > now:
            continue
        if row.ends_at and row.ends_at < now:
            continue
        active.append(row)
    return active
