"""Add tv_access_codes for admin-issued TV unlock IDs

Revision ID: 0046
Revises: 0045_favorites_allow_series
Create Date: 2026-09-14

Admin creates a short TV ID with an expiry. Entering that ID on the TV app
signs into a linked user that has an active subscription until expires_at.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tv_access_codes (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code        TEXT NOT NULL UNIQUE,
            label       TEXT,
            user_id     UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            expires_at  TIMESTAMPTZ NOT NULL,
            is_active   BOOLEAN NOT NULL DEFAULT true,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tv_access_codes_expires_at ON tv_access_codes (expires_at);"
    )
    op.execute("ALTER TABLE tv_access_codes ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON tv_access_codes FROM anon, authenticated")
    op.execute("GRANT ALL ON TABLE tv_access_codes TO service_role")
    op.execute(
        """
        DROP POLICY IF EXISTS no_direct_client_access ON public.tv_access_codes;
        CREATE POLICY no_direct_client_access ON public.tv_access_codes
          FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tv_access_codes;")
