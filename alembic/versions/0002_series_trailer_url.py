"""Add trailer_url to series

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("series", sa.Column("trailer_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("series", "trailer_url")
