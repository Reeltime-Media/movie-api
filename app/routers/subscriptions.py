import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.apps import REELTIME, AppName
from app.core.exceptions import NotFoundError
from app.dependencies import CurrentUser, DBSession
from app.models.subscription import Subscription
from app.schemas.subscription import SubscriptionRead
from app.schemas.subscription_plan import PlanAudience, SubscriptionPlanRead
from app.services.subscription_plans import list_subscription_plans

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/plans", response_model=list[SubscriptionPlanRead])
async def list_public_subscription_plans(
    db: DBSession,
    audience: PlanAudience = "app",
    app: AppName = Query(default=REELTIME),
):
    """Plans on sale. Phones and the web get the default ``app`` list; the TV app asks
    for ``?audience=tv`` and gets its own 3/6/12-month packages. ``app`` picks
    Reeltime (default) or TV5."""
    return await list_subscription_plans(db, active_only=True, app=app, audience=audience)


@router.get("/me", response_model=list[SubscriptionRead])
async def get_my_subscriptions(
    db: DBSession,
    current_user: CurrentUser,
    app: AppName = Query(default=REELTIME),
):
    """The signed-in user's subscriptions for one app (Reeltime unless ``?app=tv5``).

    Apps released before TV5 had its own plan treat any active row here as a Reeltime
    subscription, so a TV5 row must never show up without being asked for."""
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == current_user.id,
            Subscription.app == app,
        )
    )
    return result.scalars().all()


@router.get("/{subscription_id}", response_model=SubscriptionRead)
async def get_subscription(subscription_id: uuid.UUID, db: DBSession, current_user: CurrentUser):
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
