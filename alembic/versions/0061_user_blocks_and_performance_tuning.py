"""Add index on user_blocks.blocked_id and autovacuum tuning

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-05

1. Adds index on user_blocks.blocked_id to accelerate foreign key lookups and ON DELETE CASCADE cascades.
2. Tunes autovacuum thresholds on small, high-churn tables (hero_featured_items, home_section_items, watch_progress, free_today_items).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0061"
down_revision: Union[str, None] = "0060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Foreign key index on user_blocks.blocked_id
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_blocks_blocked_id
        ON user_blocks (blocked_id)
        """
    )

    # 2. Autovacuum storage tuning for high-churn metadata tables
    op.execute(
        "ALTER TABLE public.hero_featured_items SET (autovacuum_vacuum_threshold = 10, autovacuum_vacuum_scale_factor = 0.05)"
    )
    op.execute(
        "ALTER TABLE public.home_section_items SET (autovacuum_vacuum_threshold = 10, autovacuum_vacuum_scale_factor = 0.05)"
    )
    op.execute(
        "ALTER TABLE public.watch_progress SET (autovacuum_vacuum_threshold = 25, autovacuum_vacuum_scale_factor = 0.05)"
    )
    op.execute(
        "ALTER TABLE public.free_today_items SET (autovacuum_vacuum_threshold = 10, autovacuum_vacuum_scale_factor = 0.05)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_blocks_blocked_id")
