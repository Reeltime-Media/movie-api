"""Add coming_soon_items for admin-curated upcoming movie rail

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-14

Curated home-page rail for titles that are not fully published yet
(poster + metadata). Max 20 rows, enforced at the API layer.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS coming_soon_items (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content_id  UUID NOT NULL UNIQUE,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_coming_soon_items_sort "
        "ON coming_soon_items (sort_order)"
    )
    op.execute("ALTER TABLE coming_soon_items ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON coming_soon_items FROM anon, authenticated")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON coming_soon_items TO service_role"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coming_soon_items")
