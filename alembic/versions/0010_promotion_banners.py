"""Add promotion_banners table for client home promos

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE promotion_banners (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title           TEXT NOT NULL,
            subtitle        TEXT,
            image_key       TEXT,
            cta_label       TEXT,
            cta_href        TEXT,
            placement       TEXT NOT NULL DEFAULT 'home',
            is_active       BOOLEAN NOT NULL DEFAULT true,
            sort_order      INTEGER NOT NULL DEFAULT 0,
            starts_at       TIMESTAMPTZ,
            ends_at         TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_promotion_banners_active
            ON promotion_banners (placement, is_active, sort_order);
        """
    )
    op.execute("ALTER TABLE promotion_banners ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON promotion_banners FROM anon, authenticated")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON promotion_banners TO service_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS promotion_banners")
