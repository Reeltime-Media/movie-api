"""Add subscription_plans table

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("billing_interval_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.execute(
        """
        INSERT INTO subscription_plans (
            id, code, name, description, price_usd, billing_interval_days, is_active, sort_order
        ) VALUES (
            gen_random_uuid(),
            'series_monthly',
            'Reeltime Plus',
            'Full access to all series on Reeltime',
            6.99,
            30,
            true,
            0
        )
        """
    )


def downgrade() -> None:
    op.drop_table("subscription_plans")
