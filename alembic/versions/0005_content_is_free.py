"""Add is_free flag to content (episodes)

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "content",
        sa.Column("is_free", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.execute(
        """
        UPDATE content
        SET is_free = true
        WHERE type = 'episode' AND episode_number IS NOT NULL AND episode_number <= 3
        """
    )


def downgrade() -> None:
    op.drop_column("content", "is_free")
