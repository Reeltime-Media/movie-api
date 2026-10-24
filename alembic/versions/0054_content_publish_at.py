"""Add content.publish_at for scheduled movie publishing

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-24

Nullable go-live time for movies with status=scheduled. Stored UTC;
admin UI displays Cambodia (ICT).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE content ADD COLUMN IF NOT EXISTS publish_at TIMESTAMPTZ NULL")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_content_publish_at_due
          ON content (publish_at)
          WHERE is_published = false
            AND type = 'single'
            AND publish_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_content_publish_at_due")
    op.execute("ALTER TABLE content DROP COLUMN IF EXISTS publish_at")
