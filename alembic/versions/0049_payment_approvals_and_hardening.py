"""Payment approval audit + hardening follow-up

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_approvals (
            id UUID PRIMARY KEY,
            intent_id TEXT NOT NULL REFERENCES payment_intents (intent_id),
            admin_user_id UUID NOT NULL REFERENCES users (id),
            bank TEXT NOT NULL DEFAULT 'manual_bakong',
            bank_reference TEXT,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payment_approvals_intent_id "
        "ON payment_approvals (intent_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payment_approvals_admin_user_id "
        "ON payment_approvals (admin_user_id)"
    )
    op.execute("ALTER TABLE payment_approvals ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE payment_approvals FROM anon, authenticated")
    op.execute(
        "CREATE POLICY payment_approvals_deny_all ON payment_approvals "
        "FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payment_approvals_admin_user_id")
    op.execute("DROP INDEX IF EXISTS ix_payment_approvals_intent_id")
    op.execute("DROP TABLE IF EXISTS payment_approvals")
