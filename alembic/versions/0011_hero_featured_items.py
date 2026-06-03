"""Add hero_featured_items for admin-curated home hero carousel

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE hero_featured_items (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content_type    TEXT NOT NULL CHECK (content_type IN ('movie', 'series')),
            content_id      UUID NOT NULL,
            placement       TEXT NOT NULL DEFAULT 'home',
            is_active       BOOLEAN NOT NULL DEFAULT true,
            sort_order      INTEGER NOT NULL DEFAULT 0,
            starts_at       TIMESTAMPTZ,
            ends_at         TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (placement, content_type, content_id)
        );
        CREATE INDEX idx_hero_featured_items_active
            ON hero_featured_items (placement, is_active, sort_order);
        """
    )
    op.execute("ALTER TABLE hero_featured_items ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON hero_featured_items FROM anon, authenticated")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON hero_featured_items TO service_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hero_featured_items")
