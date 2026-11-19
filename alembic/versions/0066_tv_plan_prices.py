"""TV packages: launch prices and bonus time.

3 months $15; 6 months + 1 month free $27 (7 months of access); 12 months + 2 months
free $50 (14 months of access). ``bonus_days`` records the free part (it is already
inside ``billing_interval_days``) so the TV can show "6 months + 1 month free".

Each value is only changed while it still has the default migration 0065 created, so
anything already edited in the admin screen is left alone.

Revision ID: 0066
Revises: 0065
Create Date: 2026-11-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0066"
down_revision: Union[str, None] = "0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# code, old price, new price, old days, new days (incl. bonus), bonus days
_PLANS = (
    ("tv_3m", "6.99", "15.00", 90, 90, 0),
    ("tv_6m", "12.99", "27.00", 180, 210, 30),
    ("tv_12m", "22.99", "50.00", 365, 425, 60),
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE subscription_plans ADD COLUMN IF NOT EXISTS bonus_days INTEGER NOT NULL DEFAULT 0"
    )
    for code, old_price, new_price, old_days, new_days, bonus in _PLANS:
        op.execute(
            f"UPDATE subscription_plans SET price_usd = {new_price} "
            f"WHERE code = '{code}' AND price_usd = {old_price}"
        )
        op.execute(
            f"UPDATE subscription_plans SET billing_interval_days = {new_days}, bonus_days = {bonus} "
            f"WHERE code = '{code}' AND billing_interval_days = {old_days}"
        )


def downgrade() -> None:
    for code, old_price, new_price, old_days, new_days, _bonus in _PLANS:
        op.execute(
            f"UPDATE subscription_plans SET price_usd = {old_price} "
            f"WHERE code = '{code}' AND price_usd = {new_price}"
        )
        op.execute(
            f"UPDATE subscription_plans SET billing_interval_days = {old_days} "
            f"WHERE code = '{code}' AND billing_interval_days = {new_days}"
        )
    op.execute("ALTER TABLE subscription_plans DROP COLUMN IF EXISTS bonus_days")
