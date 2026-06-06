"""Add banner_key to series for wide hero images

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE series ADD COLUMN banner_key TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE series DROP COLUMN banner_key;")
