from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.subscription_plan import SubscriptionPlan


async def list_subscription_plans(
    db: AsyncSession,
    *,
    active_only: bool = False,
    audience: str | None = None,
) -> list[SubscriptionPlan]:
    """Plans in display order. ``audience`` ("app" or "tv") narrows to one storefront;
    None returns every plan (the admin list)."""
    stmt = select(SubscriptionPlan).order_by(
        SubscriptionPlan.sort_order.asc(),
        SubscriptionPlan.created_at.asc(),
    )
    if active_only:
        stmt = stmt.where(SubscriptionPlan.is_active.is_(True))
    if audience is not None:
        stmt = stmt.where(SubscriptionPlan.audience == audience)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_subscription_plan_by_code(
    db: AsyncSession,
    code: str,
) -> SubscriptionPlan | None:
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == code))
    return result.scalar_one_or_none()


async def resolve_active_plan(
    db: AsyncSession,
    plan_code: str | None = None,
) -> SubscriptionPlan:
    if plan_code:
        plan = await get_subscription_plan_by_code(db, plan_code)
        if not plan or not plan.is_active:
            raise NotFoundError("Subscription plan not found")
        return plan

    # The default plan is a phone/web plan; TV packages are only bought by naming them.
    result = await db.execute(
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active.is_(True), SubscriptionPlan.audience == "app")
        .order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.created_at.asc())
        .limit(1)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("No active subscription plan configured")
    return plan
