"""Add region column to content

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-09

Stores the movie/episode's country or region of origin (e.g. Khmer,
Hollywood, Korean, Chinese), kept separate from the free-form `genres`
tags which previously conflated category and region.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE content ADD COLUMN IF NOT EXISTS region TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE content DROP COLUMN IF EXISTS region")
