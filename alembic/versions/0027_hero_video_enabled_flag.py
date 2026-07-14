"""Per-slide toggle for hero video playback

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-14

Catalog hero slides auto-play the title's trailer. video_enabled lets admins
turn that off per slide and show just the banner.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hero_featured_items "
        "ADD COLUMN IF NOT EXISTS video_enabled BOOLEAN NOT NULL DEFAULT TRUE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE hero_featured_items DROP COLUMN IF EXISTS video_enabled")
