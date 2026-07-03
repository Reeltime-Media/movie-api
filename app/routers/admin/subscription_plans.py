import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.subscription_plan import (
    SubscriptionPlanCreate,
    SubscriptionPlanRead,
    SubscriptionPlanUpdate,
)
from app.services.subscription_plans import list_subscription_plans

router = APIRouter()


@router.get("/subscription-plans", response_model=list[SubscriptionPlanRead])
async def list_admin_subscription_plans(db: DBSession, _: AdminUser):
    try:
        return await list_subscription_plans(db)
    except Exception as exc:
        message = str(exc).lower()
        if "subscription_plans" in message or "does not exist" in message or "undefinedtable" in message:
            raise HTTPException(
                status_code=503,
                detail=(
                    "subscription_plans table is missing. "
                    "Run: cd movie-api && alembic upgrade head"
                ),
            ) from exc
        raise HTTPException(status_code=500, detail="Could not load subscription plans") from exc


@router.post("/subscription-plans", response_model=SubscriptionPlanRead, status_code=201)
async def create_admin_subscription_plan(
    data: SubscriptionPlanCreate,
    db: DBSession,
    _: AdminUser,
):
    existing = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.code == data.code)
    )
    if existing.scalar_one_or_none():
        raise ConflictError("A plan with this code already exists")

    plan = SubscriptionPlan(**data.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.patch("/subscription-plans/{plan_id}", response_model=SubscriptionPlanRead)
async def update_admin_subscription_plan(
    plan_id: uuid.UUID,
    data: SubscriptionPlanUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Subscription plan not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)

    await db.commit()
    await db.refresh(plan)
    return plan


@router.delete("/subscription-plans/{plan_id}", status_code=204)
async def delete_admin_subscription_plan(
    plan_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Subscription plan not found")

    in_use = await db.scalar(
        select(func.count(Subscription.id)).where(Subscription.plan == plan.code)
    )
    if in_use:
        raise ConflictError(
            "This plan has active subscriptions and cannot be deleted. Deactivate it instead."
        )

    await db.delete(plan)
    await db.commit()
