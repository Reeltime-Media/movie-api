"""Add Sign in with Apple IDs and comment author blocks

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-02

Idempotent, like the other recent migrations.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0059"
down_revision: Union[str, None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS apple_id TEXT NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_apple_id_key ON users (apple_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_blocks (
            blocker_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            blocked_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (blocker_id, blocked_id)
        );
        """
    )
    op.execute("ALTER TABLE user_blocks ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON user_blocks FROM anon, authenticated")
    op.execute("GRANT ALL ON TABLE user_blocks TO service_role")
    op.execute(
        """
        DROP POLICY IF EXISTS no_direct_client_access ON public.user_blocks;
        CREATE POLICY no_direct_client_access ON public.user_blocks
            FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_blocks")
    op.execute("DROP INDEX IF EXISTS users_apple_id_key")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS apple_id")
