"""
Grant (comp) a subscription to existing users by email — no payment involved.

Dry run (default, writes nothing):

    PYTHONPATH=. env/bin/python scripts/grant_subscription.py a@x.com b@y.com

Apply:

    PYTHONPATH=. env/bin/python scripts/grant_subscription.py --apply a@x.com b@y.com

Options:
    --plan CODE   plan to grant (default: best_value_3m, 90 days)
    --days N      override the plan's billing_interval_days

Mirrors payment fulfillment: if the user already has time left, the grant is
added on after their current period end; otherwise it starts now. The user's
latest subscription row is updated in place rather than adding a second one —
`user_has_active_subscription` uses scalar_one_or_none() and would raise on
two active rows. No SubscriptionPayment row is written, so comps don't show up
as revenue.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.subscription import Subscription
from app.models.user import User
from app.services.subscription_plans import resolve_active_plan


async def grant(emails: list[str], plan_code: str, days: int | None, apply: bool) -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(settings.effective_database_url, debug=False),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime.now(timezone.utc)

    async with session_factory() as db:
        plan = await resolve_active_plan(db, plan_code)
        grant_days = days or plan.billing_interval_days
        print(f"Plan: {plan.code} ({plan.name}), granting {grant_days} days")
        print(f"Mode: {'APPLY' if apply else 'DRY RUN — nothing will be written'}\n")

        granted = 0
        missing: list[str] = []
        for email in emails:
            user = await db.scalar(
                select(User).where(func.lower(User.email) == email.strip().lower())
            )
            if not user:
                missing.append(email)
                print(f"  {email}: NO ACCOUNT — skipped")
                continue

            subscription = (
                await db.scalars(
                    select(Subscription)
                    .where(Subscription.user_id == user.id)
                    .order_by(Subscription.current_period_end.desc())
                )
            ).first()

            if subscription and subscription.current_period_end > now:
                period_start = subscription.current_period_end
                note = f"extends current period ending {period_start:%Y-%m-%d}"
            else:
                period_start = now
                note = "starts now"
            period_end = period_start + timedelta(days=grant_days)

            if not subscription:
                db.add(
                    Subscription(
                        user_id=user.id,
                        plan=plan.code,
                        status="active",
                        current_period_start=now,
                        current_period_end=period_end,
                    )
                )
            else:
                subscription.status = "active"
                subscription.plan = plan.code
                if subscription.current_period_end <= now:
                    subscription.current_period_start = now
                subscription.current_period_end = period_end

            granted += 1
            disabled = "" if user.is_active else "  [account is DISABLED]"
            print(f"  {email}: active until {period_end:%Y-%m-%d} ({note}){disabled}")

        if apply:
            await db.commit()
        else:
            await db.rollback()

    await engine.dispose()

    verb = "Granted" if apply else "Would grant"
    print(f"\n{verb} {granted} subscription(s).")
    if missing:
        print(f"No account for: {', '.join(missing)} — they must sign up first, then re-run.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("emails", nargs="+")
    parser.add_argument("--plan", default="best_value_3m")
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(grant(args.emails, args.plan, args.days, args.apply))


if __name__ == "__main__":
    main()
