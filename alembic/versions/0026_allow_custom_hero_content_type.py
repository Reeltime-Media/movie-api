"""Allow custom hero slides in the content_type check constraint

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-13

Migration 0011 created hero_featured_items with an inline CHECK limiting
content_type to ('movie', 'series'). Custom slides need 'custom' allowed too.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "hero_featured_items_content_type_check"


def upgrade() -> None:
    op.execute(f"ALTER TABLE hero_featured_items DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE hero_featured_items ADD CONSTRAINT {_CONSTRAINT} "
        "CHECK (content_type IN ('movie', 'series', 'custom'))"
    )


def downgrade() -> None:
    # Custom rows cannot survive the movie/series-only constraint.
    op.execute("DELETE FROM hero_featured_items WHERE content_type = 'custom'")
    op.execute(f"ALTER TABLE hero_featured_items DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE hero_featured_items ADD CONSTRAINT {_CONSTRAINT} "
        "CHECK (content_type IN ('movie', 'series'))"
    )
