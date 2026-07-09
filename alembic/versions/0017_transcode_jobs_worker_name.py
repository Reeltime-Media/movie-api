"""Add worker_name to transcode_jobs for instance tracking

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-06
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE transcode_jobs ADD COLUMN IF NOT EXISTS worker_name TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE transcode_jobs DROP COLUMN IF EXISTS worker_name")
