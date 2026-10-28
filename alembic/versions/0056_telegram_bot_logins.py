"""Telegram bot sign-in codes (phone app taps Start + Confirm in the bot)

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_bot_logins (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code_hash            TEXT NOT NULL UNIQUE,
            status               TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'started', 'confirmed', 'used', 'expired')),
            telegram_id          TEXT,
            telegram_first_name  TEXT,
            telegram_last_name   TEXT,
            telegram_username    TEXT,
            expires_at           TIMESTAMPTZ NOT NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("ALTER TABLE telegram_bot_logins ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON telegram_bot_logins FROM anon, authenticated")
    op.execute("GRANT ALL ON TABLE telegram_bot_logins TO service_role")
    op.execute(
        """
        DROP POLICY IF EXISTS no_direct_client_access ON public.telegram_bot_logins;
        CREATE POLICY no_direct_client_access ON public.telegram_bot_logins
            FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS telegram_bot_logins")
