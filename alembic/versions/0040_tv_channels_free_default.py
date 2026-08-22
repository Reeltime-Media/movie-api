"""Make live TV free by default; flip existing channels to free.

Revision ID: 0040_tv_channels_free_default
Revises: 0039_ratings
Create Date: 2026-08-22
"""

from alembic import op

revision = "0040_tv_channels_free_default"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE tv_channels SET is_free = true WHERE is_free = false")
    op.execute("ALTER TABLE tv_channels ALTER COLUMN is_free SET DEFAULT true")


def downgrade() -> None:
    op.execute("ALTER TABLE tv_channels ALTER COLUMN is_free SET DEFAULT false")
