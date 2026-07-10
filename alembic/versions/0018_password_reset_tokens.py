"""Add password_reset_tokens table for forgot-password flow

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE password_reset_tokens (
            id          UUID PRIMARY KEY,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash  TEXT NOT NULL UNIQUE,
            expires_at  TIMESTAMPTZ NOT NULL,
            used_at     TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_password_reset_tokens_user_id ON password_reset_tokens(user_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS password_reset_tokens;")
