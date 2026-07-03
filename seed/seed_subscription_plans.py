"""
Seed 3 subscription plans (idempotent).

    python seed_subscription_plans.py

Safe to run in Docker:

    docker compose exec api python seed_subscription_plans.py

Skips any plan whose code already exists. Re-running is safe.
"""

import asyncio
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.subscription_plan import SubscriptionPlan

SEED_PLANS: list[dict] = [
    {
        "code": "basic_monthly",
        "name": "Basic",
        "description": "Great for casual viewers. Stream all series on one device with standard quality. New episodes added every week.",
        "price_usd": Decimal("3.99"),
        "billing_interval_days": 30,
        "is_active": True,
        "sort_order": 0,
    },
    {
        "code": "standard_monthly",
        "name": "Standard",
        "description": "Our most popular plan. HD streaming on up to 2 devices, full series library, no per-title fees, and early access to new releases.",
        "price_usd": Decimal("6.99"),
        "billing_interval_days": 30,
        "is_active": True,
        "sort_order": 1,
    },
    {
        "code": "premium_annual",
        "name": "Premium Annual",
        "description": "Best value — over 2 months free. 4K streaming on up to 4 devices, offline downloads, priority support, and every title the moment it drops.",
        "price_usd": Decimal("59.99"),
        "billing_interval_days": 365,
        "is_active": True,
        "sort_order": 2,
    },
]


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        added = 0
        for row in SEED_PLANS:
            existing = await db.scalar(
                select(SubscriptionPlan).where(SubscriptionPlan.code == row["code"])
            )
            if existing:
                print(f"  skip (exists): {row['code']}")
                continue
            db.add(SubscriptionPlan(**row))
            added += 1
            print(f"  added: {row['code']} — {row['name']} ${row['price_usd']}")

        await db.commit()
        print(f"\nDone. Seeded {added} plan(s).")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
