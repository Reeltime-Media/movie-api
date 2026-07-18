"""Add free_today_items for admin-curated free movie picks

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-14

Movies listed here are genuinely free to watch while listed (entitlement
override in content_access). Max 10 rows, enforced at the API layer.

Idempotent: table may already exist if applied outside Alembic.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS free_today_items (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content_id  UUID NOT NULL UNIQUE,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_free_today_items_sort "
        "ON free_today_items (sort_order)"
    )
    op.execute("ALTER TABLE free_today_items ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON free_today_items FROM anon, authenticated")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON free_today_items TO service_role"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS free_today_items")
