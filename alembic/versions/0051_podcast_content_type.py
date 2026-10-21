"""Allow content.type=podcast and add audio_key

Revision ID: 0051
Revises: 0050
Create Date: 2026-10-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres names unnamed column CHECKs as {table}_{column}_check.
    op.execute("ALTER TABLE content DROP CONSTRAINT IF EXISTS content_type_check")
    op.execute(
        """
        ALTER TABLE content
        ADD CONSTRAINT content_type_check
        CHECK (type IN ('single', 'episode', 'podcast'))
        """
    )

    op.execute("ALTER TABLE content DROP CONSTRAINT IF EXISTS single_has_price")
    op.execute(
        """
        ALTER TABLE content
        ADD CONSTRAINT single_has_price CHECK (
          (type = 'single' AND price_usd IS NOT NULL AND series_id IS NULL)
          OR (type = 'episode' AND series_id IS NOT NULL AND price_usd IS NULL)
          OR (type = 'podcast' AND price_usd IS NOT NULL AND series_id IS NULL)
        )
        """
    )

    op.execute("ALTER TABLE content ADD COLUMN IF NOT EXISTS audio_key TEXT")


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM content WHERE type = 'podcast'
        """
    )
    op.execute("ALTER TABLE content DROP COLUMN IF EXISTS audio_key")

    op.execute("ALTER TABLE content DROP CONSTRAINT IF EXISTS single_has_price")
    op.execute(
        """
        ALTER TABLE content
        ADD CONSTRAINT single_has_price CHECK (
          (type = 'single' AND price_usd IS NOT NULL AND series_id IS NULL)
          OR (type = 'episode' AND series_id IS NOT NULL AND price_usd IS NULL)
        )
        """
    )

    op.execute("ALTER TABLE content DROP CONSTRAINT IF EXISTS content_type_check")
    op.execute(
        """
        ALTER TABLE content
        ADD CONSTRAINT content_type_check
        CHECK (type IN ('single', 'episode'))
        """
    )
