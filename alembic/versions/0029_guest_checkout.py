"""Guest checkout — nullable user_id + guest_id on payment_intents/purchases

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-18

Lets an unauthenticated buyer purchase a movie: the intent/purchase row is
keyed by an anonymous `guest_id` cookie token instead of `user_id`. Same shape
as 0008_user_google_auth making `users.password_hash` nullable for a second
auth path.

Idempotent: columns/indexes may already exist if applied outside Alembic.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payment_intents ALTER COLUMN user_id DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE payment_intents ADD COLUMN IF NOT EXISTS guest_id TEXT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payment_intents_guest_id "
        "ON payment_intents (guest_id)"
    )

    op.execute("ALTER TABLE purchases ALTER COLUMN user_id DROP NOT NULL")
    op.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS guest_id TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_purchases_guest_id ON purchases (guest_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_purchases_guest_id")
    op.execute("ALTER TABLE purchases DROP COLUMN IF EXISTS guest_id")
    op.execute("ALTER TABLE purchases ALTER COLUMN user_id SET NOT NULL")

    op.execute("DROP INDEX IF EXISTS ix_payment_intents_guest_id")
    op.execute("ALTER TABLE payment_intents DROP COLUMN IF EXISTS guest_id")
    op.execute("ALTER TABLE payment_intents ALTER COLUMN user_id SET NOT NULL")
