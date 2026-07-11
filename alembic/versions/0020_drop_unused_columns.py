"""Drop unused search_vector and billing stub columns

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_content_search")
    op.execute("ALTER TABLE content DROP COLUMN IF EXISTS search_vector")
    op.execute("ALTER TABLE purchases DROP COLUMN IF EXISTS expires_at")
    op.execute("ALTER TABLE purchases DROP COLUMN IF EXISTS first_played_at")
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS reminder_sent_at")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE content ADD COLUMN IF NOT EXISTS search_vector tsvector
          GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(title,'') || ' ' || coalesce(description,''))
          ) STORED
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_search ON content USING GIN (search_vector)"
    )
    op.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ")
    op.execute(
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS first_played_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ"
    )
