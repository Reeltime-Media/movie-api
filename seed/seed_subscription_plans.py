"""
Upsert Reeltime subscription plans (idempotent).

    PYTHONPATH=. python seed/seed_subscription_plans.py

Safe to run in Docker:

    docker compose exec -e PYTHONPATH=/app api python seed/seed_subscription_plans.py

Creates or updates the four current plans. Deactivates legacy plan codes.
Re-running is safe.
"""

import asyncio
import sys
from pathlib import Path

# Host runs from movie-api/; Docker runs `python seed/seed_*.py` with script dir first.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.subscription_plan import SubscriptionPlan
from seed.pricing_catalog import SEED_PLANS, apply_plan_fields, seed_plan_codes


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        added = 0
        updated = 0
        for row in SEED_PLANS:
            existing = await db.scalar(
                select(SubscriptionPlan).where(SubscriptionPlan.code == row["code"])
            )
            if existing:
                changed = apply_plan_fields(existing, row)
                if changed:
                    updated += 1
                    print(f"  updated: {row['code']} — {row['name']} ${row['price_usd']}")
                else:
                    print(f"  skip (unchanged): {row['code']}")
                continue
            db.add(SubscriptionPlan(**row))
            added += 1
            print(f"  added: {row['code']} — {row['name']} ${row['price_usd']}")

        deactivated = 0
        keep = seed_plan_codes()
        extras = (
            await db.scalars(
                select(SubscriptionPlan).where(SubscriptionPlan.code.notin_(keep))
            )
        ).all()
        for plan in extras:
            if plan.is_active:
                plan.is_active = False
                deactivated += 1
                print(f"  deactivated: {plan.code}")
            else:
                print(f"  skip (already inactive): {plan.code}")

        await db.commit()
        print(
            f"\nDone. Added {added}, updated {updated}, deactivated {deactivated} plan(s)."
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
