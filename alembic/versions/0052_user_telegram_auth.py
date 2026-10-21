"""Telegram auth fields and short-lived login nonces

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS telegram_id TEXT;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_id
        ON users (telegram_id)
        WHERE telegram_id IS NOT NULL;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_auth_nonces (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            nonce_hash  TEXT NOT NULL UNIQUE,
            status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'used', 'expired')),
            expires_at  TIMESTAMPTZ NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("ALTER TABLE telegram_auth_nonces ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON telegram_auth_nonces FROM anon, authenticated")
    op.execute("GRANT ALL ON TABLE telegram_auth_nonces TO service_role")
    op.execute(
        """
        DROP POLICY IF EXISTS no_direct_client_access ON public.telegram_auth_nonces;
        CREATE POLICY no_direct_client_access ON public.telegram_auth_nonces
            FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS telegram_auth_nonces")
    op.execute("DROP INDEX IF EXISTS ix_users_telegram_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS telegram_id")
