"""Add covering indexes for unindexed foreign keys

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-11

Addresses Supabase linter unindexed_foreign_keys. Intentionally does not drop
"unused" hot-path indexes from 0016 — they are unused due to low traffic, not
because they are wrong.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = (
    ("ix_comment_reports_comment_id", "comment_reports", "comment_id"),
    ("ix_favorites_content_id", "favorites", "content_id"),
    ("ix_payment_intents_content_id", "payment_intents", "content_id"),
    ("ix_payment_intents_user_id", "payment_intents", "user_id"),
    ("ix_purchases_content_id", "purchases", "content_id"),
    ("ix_subscription_payments_subscription_id", "subscription_payments", "subscription_id"),
    ("ix_watch_progress_content_id", "watch_progress", "content_id"),
)


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON public.{table} ({column})"
        )


def downgrade() -> None:
    for name, _table, _column in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
