"""Rotate tokens on refresh

Revision ID: 0060
Revises: 0059
Create Date: 2026-11-02

token_version is bumped by every POST /auth/refresh, and only a token carrying
the current value may refresh again. Existing sessions start at 0, which is
what tokens issued before this carry. Idempotent, like the other recent
migrations.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0060"
down_revision: Union[str, None] = "0059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS refreshed_at TIMESTAMPTZ NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS refreshed_at")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS token_version")
