"""Add banner_key to content for wide hero images

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE content ADD COLUMN banner_key TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE content DROP COLUMN banner_key;")
