"""TV subscription packages: plan audience + the 3/6/12-month TV plans.

``subscription_plans.audience`` says which storefront sells a plan: "app" (phone/web,
every existing plan) or "tv" (the TV app). The public plan list only returns "app" plans
unless ``?audience=tv`` is asked for, so the TV packages never show up on phones or the
website.

Revision ID: 0065
Revises: 0064
Create Date: 2026-11-18
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0065"
down_revision: Union[str, None] = "0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TV_PLANS = (
    # code, name, price, days, sort_order, months
    ("tv_3m", "TV 3 Months", "6.99", 90, 10, 3),
    ("tv_6m", "TV 6 Months", "12.99", 180, 11, 6),
    ("tv_12m", "TV 12 Months", "22.99", 365, 12, 12),
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE subscription_plans ADD COLUMN IF NOT EXISTS audience TEXT NOT NULL DEFAULT 'app'"
    )
    for code, name, price, days, sort_order, months in _TV_PLANS:
        description = f"{months} months. Access to Series, Movies, Podcast, and News."
        op.execute(
            f"""
            INSERT INTO subscription_plans (
                id, code, name, description, price_usd, billing_interval_days,
                is_active, sort_order, audience
            ) VALUES (
                gen_random_uuid(), '{code}', '{name}', '{description}', {price}, {days},
                true, {sort_order}, 'tv'
            )
            ON CONFLICT (code) DO NOTHING
            """
        )


def downgrade() -> None:
    op.execute("DELETE FROM subscription_plans WHERE code IN ('tv_3m', 'tv_6m', 'tv_12m')")
    op.execute("ALTER TABLE subscription_plans DROP COLUMN IF EXISTS audience")
