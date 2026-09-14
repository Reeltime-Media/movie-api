"""Allow favouriting series as well as single movies.

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-10

favorites.content_id used to FK content.id, so a series UUID could never be
stored. Drop that FK and let the app accept a published movie or series id.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE favorites DROP CONSTRAINT IF EXISTS favorites_content_id_fkey"
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM favorites
        WHERE content_id NOT IN (SELECT id FROM content)
        """
    )
    op.execute(
        """
        ALTER TABLE favorites
        ADD CONSTRAINT favorites_content_id_fkey
        FOREIGN KEY (content_id) REFERENCES content(id) ON DELETE CASCADE
        """
    )
