"""Add per-section item limit to home_sections

Revision ID: 0058
Revises: 0057
Create Date: 2026-11-01

NULL keeps the default from SECTION_CAPS, so existing sections do not change.
Idempotent: the column may already exist if applied outside Alembic.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE home_sections ADD COLUMN IF NOT EXISTS item_limit INTEGER NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE home_sections DROP COLUMN IF EXISTS item_limit")
