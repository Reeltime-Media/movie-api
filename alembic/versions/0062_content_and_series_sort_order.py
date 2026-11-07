"""Add sort_order to content and series tables for catalog ordering.

Revision ID: 0062
Revises: 0061
Create Date: 2026-11-07
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0062"
down_revision: Union[str, None] = "0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add sort_order to content table
    op.execute(
        """
        ALTER TABLE content
        ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;
        """
    )

    # 2. Add sort_order to series table
    op.execute(
        """
        ALTER TABLE series
        ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;
        """
    )

    # 3. Create index for movie catalog queries: (type, is_published, sort_order, created_at DESC)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_content_catalog_order
        ON content (type, is_published, sort_order, created_at DESC);
        """
    )

    # 4. Create index for series catalog queries: (is_published, is_short_movie, sort_order, created_at DESC)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_series_catalog_order
        ON series (is_published, is_short_movie, sort_order, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_content_catalog_order;")
    op.execute("DROP INDEX IF EXISTS ix_series_catalog_order;")
    op.execute("ALTER TABLE content DROP COLUMN IF EXISTS sort_order;")
    op.execute("ALTER TABLE series DROP COLUMN IF EXISTS sort_order;")
