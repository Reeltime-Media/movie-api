"""Bakong KHQR inline checkout — method + bakong_md5 on payment_intents

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-18

Bakong has no webhook — we poll `check_transaction_by_md5` ourselves, keyed by
the md5 of the generated KHQR string. `method` distinguishes which provider an
intent belongs to; existing rows backfill to 'baray' (the only provider until now).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep server_default permanently — ORM inserts that omit `method` must not
    # fail NOT NULL (Python `default=` alone is not always emitted on INSERT).
    op.execute(
        "ALTER TABLE payment_intents "
        "ADD COLUMN IF NOT EXISTS method TEXT NOT NULL DEFAULT 'baray'"
    )
    # Restore default if an earlier revision added the column then dropped it.
    op.execute(
        "ALTER TABLE payment_intents ALTER COLUMN method SET DEFAULT 'baray'"
    )
    op.execute(
        "UPDATE payment_intents SET method = 'baray' WHERE method IS NULL"
    )
    op.execute(
        "ALTER TABLE payment_intents "
        "ADD COLUMN IF NOT EXISTS bakong_md5 TEXT"
    )
    # The generated KHQR string embeds a creation timestamp, so it can't be
    # deterministically re-derived later — persist it verbatim to redisplay
    # the exact same QR (and matching md5) on a repeat "pending intent" fetch.
    op.execute(
        "ALTER TABLE payment_intents "
        "ADD COLUMN IF NOT EXISTS bakong_qr TEXT"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_payment_intents_bakong_md5
        ON payment_intents (bakong_md5)
        WHERE bakong_md5 IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payment_intents_bakong_md5")
    op.execute("ALTER TABLE payment_intents DROP COLUMN IF EXISTS bakong_qr")
    op.execute("ALTER TABLE payment_intents DROP COLUMN IF EXISTS bakong_md5")
    op.execute("ALTER TABLE payment_intents DROP COLUMN IF EXISTS method")
