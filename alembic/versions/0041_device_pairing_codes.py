"""Add device_pairing_codes table for TV QR sign-in

Revision ID: 0041
Revises: 0040_tv_channels_free_default
Create Date: 2026-08-28

A TV requests a short-lived code, shows it as a QR code, and polls for
confirmation once an already-authenticated phone browser confirms it.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040_tv_channels_free_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE device_pairing_codes (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code_hash   TEXT NOT NULL UNIQUE,
            status      TEXT NOT NULL DEFAULT 'pending',
            token       TEXT,
            user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
            expires_at  TIMESTAMPTZ NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("ALTER TABLE device_pairing_codes ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON device_pairing_codes FROM anon, authenticated")
    op.execute("GRANT ALL ON TABLE device_pairing_codes TO service_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS device_pairing_codes;")
