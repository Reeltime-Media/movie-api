"""Hero carousel: custom slides + video fields

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-13

Adds custom-slide fields (title, description, banner_key, link_url) and promo
video fields (video_key, youtube_url) to hero_featured_items, and makes
content_id nullable so custom slides need no catalog reference.

Idempotent: columns may already exist if applied outside Alembic (e.g. a
partial deploy), so we use IF NOT EXISTS / DROP IF EXISTS.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = ("title", "description", "banner_key", "link_url", "video_key", "youtube_url")


def upgrade() -> None:
    for name in _NEW_COLUMNS:
        op.execute(
            f"ALTER TABLE hero_featured_items ADD COLUMN IF NOT EXISTS {name} TEXT"
        )
    op.execute(
        "ALTER TABLE hero_featured_items ALTER COLUMN content_id DROP NOT NULL"
    )


def downgrade() -> None:
    # Custom slides have no content_id; they cannot survive the NOT NULL restore.
    op.execute("DELETE FROM hero_featured_items WHERE content_id IS NULL")
    op.execute(
        "ALTER TABLE hero_featured_items ALTER COLUMN content_id SET NOT NULL"
    )
    for name in reversed(_NEW_COLUMNS):
        op.execute(f"ALTER TABLE hero_featured_items DROP COLUMN IF EXISTS {name}")
