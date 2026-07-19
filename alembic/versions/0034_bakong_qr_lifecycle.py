"""Bakong QR lifecycle — merchant name, prev md5, qr created_at

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-19

Supports app-level QR TTL (bakong-khqr only allows expiration in whole days,
min 1). We regenerate after BAKONG_QR_TTL_MINUTES and keep the previous md5
so a late pay on the old QR can still settle.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payment_intents "
        "ADD COLUMN IF NOT EXISTS bakong_merchant_name TEXT"
    )
    op.execute(
        "ALTER TABLE payment_intents "
        "ADD COLUMN IF NOT EXISTS bakong_prev_md5 TEXT"
    )
    op.execute(
        "ALTER TABLE payment_intents "
        "ADD COLUMN IF NOT EXISTS bakong_qr_created_at TIMESTAMPTZ"
    )
    # Backfill existing Bakong rows so TTL/sweeper treat them as issued at create time.
    op.execute(
        """
        UPDATE payment_intents
        SET bakong_qr_created_at = created_at
        WHERE method = 'bakong'
          AND bakong_qr IS NOT NULL
          AND bakong_qr_created_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_payment_intents_bakong_pending_sweep
        ON payment_intents (bakong_qr_created_at)
        WHERE method = 'bakong' AND status = 'pending' AND bakong_md5 IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payment_intents_bakong_pending_sweep")
    op.execute(
        "ALTER TABLE payment_intents DROP COLUMN IF EXISTS bakong_qr_created_at"
    )
    op.execute(
        "ALTER TABLE payment_intents DROP COLUMN IF EXISTS bakong_prev_md5"
    )
    op.execute(
        "ALTER TABLE payment_intents DROP COLUMN IF EXISTS bakong_merchant_name"
    )
