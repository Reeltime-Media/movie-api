"""Partial composite index for Bakong pending sweeper

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-11

Matches the sweeper filter (method=bakong, status=pending, bakong_md5 set)
so FOR UPDATE SKIP LOCKED polls avoid seq scans as payment_intents grows.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payment_intents_bakong_pending_sweep")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_payment_intents_bakong_pending_sweep
        ON payment_intents (method, status, bakong_qr_created_at)
        WHERE status = 'pending' AND bakong_md5 IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payment_intents_bakong_pending_sweep")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_payment_intents_bakong_pending_sweep
        ON payment_intents (bakong_qr_created_at)
        """
    )
