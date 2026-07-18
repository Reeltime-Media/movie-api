"""Add series catalog listing index

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-18

Mirrors ix_content_catalog for series list:
WHERE is_published ORDER BY created_at DESC.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_series_catalog "
        "ON series (is_published, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_series_catalog")
