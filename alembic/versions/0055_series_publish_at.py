"""Add series.status + series.publish_at for scheduled publishing

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-24

Mirrors content.publish_at for series. Stored UTC; admin UI shows ICT.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE series
          ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft'
        """
    )
    op.execute(
        """
        ALTER TABLE series
          ADD COLUMN IF NOT EXISTS publish_at TIMESTAMPTZ NULL
        """
    )
    # Backfill from the legacy boolean.
    op.execute(
        """
        UPDATE series
           SET status = 'published'
         WHERE is_published = true
           AND status = 'draft'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_series_publish_at_due
          ON series (publish_at)
          WHERE is_published = false
            AND publish_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_series_publish_at_due")
    op.execute("ALTER TABLE series DROP COLUMN IF EXISTS publish_at")
    op.execute("ALTER TABLE series DROP COLUMN IF EXISTS status")
