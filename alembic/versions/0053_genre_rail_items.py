"""Add genre_rail_items for admin-curated home genre rails

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-23

Per-genre ordered movie picks for the web home page (Horror, Action, …).
Max 12 titles per genre, enforced at the API layer.

Idempotent: table may already exist if applied outside Alembic.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS genre_rail_items (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            genre_name  TEXT NOT NULL,
            content_id  UUID NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_genre_rail_genre_content UNIQUE (genre_name, content_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_genre_rail_items_genre_sort "
        "ON genre_rail_items (genre_name, sort_order)"
    )
    op.execute("ALTER TABLE genre_rail_items ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON genre_rail_items FROM anon, authenticated")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON genre_rail_items TO service_role"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS genre_rail_items")
