"""Add composite indexes for hot query paths

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = [
    # Movie/series catalog listing: WHERE type = X AND is_published = TRUE ORDER BY created_at DESC
    ("ix_content_catalog", "content", ["type", "is_published", "created_at DESC"]),
    # Episode listing: WHERE series_id = X ORDER BY season_number, episode_number
    ("ix_content_series_episodes", "content", ["series_id", "season_number", "episode_number"]),
    # Access check on every playback: WHERE user_id = X AND content_id = Y
    ("ix_purchases_user_content", "purchases", ["user_id", "content_id"]),
    # Subscription access check: WHERE user_id = X AND status = Y AND current_period_end > now()
    ("ix_subscriptions_user_status_period", "subscriptions", ["user_id", "status", "current_period_end"]),
    # Comment threads: WHERE content_id = X AND parent_id IS NULL AND deleted_at IS NULL
    ("ix_comments_content_thread", "comments", ["content_id", "parent_id", "deleted_at"]),
    # Admin payment listing / revenue timeline: WHERE status = X ORDER BY created_at
    ("ix_payment_intents_status_created", "payment_intents", ["status", "created_at"]),
]


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        cols = ", ".join(columns)
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})")


def downgrade() -> None:
    for name, _table, _columns in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
