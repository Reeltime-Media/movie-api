import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.dependencies import CurrentUser, DBSession
from app.models.subscription import Subscription
from app.schemas.subscription import SubscriptionRead
from app.schemas.subscription_plan import SubscriptionPlanRead
from app.services.subscription_plans import list_subscription_plans

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/plans", response_model=list[SubscriptionPlanRead])
async def list_public_subscription_plans(db: DBSession):
    return await list_subscription_plans(db, active_only=True)


@router.get("/me", response_model=list[SubscriptionRead])
async def get_my_subscriptions(db: DBSession, current_user: CurrentUser):
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id)
    )
    return result.scalars().all()


@router.get("/{subscription_id}", response_model=SubscriptionRead)
async def get_subscription(
    subscription_id: uuid.UUID, db: DBSession, current_user: CurrentUser
):
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == current_user.id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise NotFoundError("Subscription not found")
    return sub
