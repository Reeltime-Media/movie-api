"""Add favorites table for user movie bookmarks

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-04
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE favorites (
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content_id  UUID NOT NULL REFERENCES content(id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, content_id)
        );
        CREATE INDEX idx_favorites_user_id ON favorites(user_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS favorites;")
