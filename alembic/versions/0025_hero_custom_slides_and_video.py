"""Hero carousel: custom slides + video fields

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-13

Adds custom-slide fields (title, description, banner_key, link_url) and promo
video fields (video_key, youtube_url) to hero_featured_items, and makes
content_id nullable so custom slides need no catalog reference.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = ("title", "description", "banner_key", "link_url", "video_key", "youtube_url")


def upgrade() -> None:
    for name in _NEW_COLUMNS:
        op.add_column("hero_featured_items", sa.Column(name, sa.Text(), nullable=True))
    op.alter_column(
        "hero_featured_items",
        "content_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Custom slides have no content_id; they cannot survive the NOT NULL restore.
    op.execute("DELETE FROM hero_featured_items WHERE content_id IS NULL")
    op.alter_column(
        "hero_featured_items",
        "content_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    for name in reversed(_NEW_COLUMNS):
        op.drop_column("hero_featured_items", name)
