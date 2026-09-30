"""P1 indexes + payment_intents.plan_code

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-30

- Composite indexes for guest movie purchases and series unlocks
- Partial index for free published episodes (catalog free= filter / badges)
- GIN indexes on content.genres / series.genres for related/overlap queries
- plan_code on payment_intents so subscription pending reuse is plan-scoped
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payment_intents ADD COLUMN IF NOT EXISTS plan_code TEXT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payment_intents_plan_code "
        "ON payment_intents (plan_code) WHERE plan_code IS NOT NULL"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_purchases_guest_content "
        "ON purchases (guest_id, content_id) WHERE guest_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_series_purchases_user_series "
        "ON series_purchases (user_id, series_id) WHERE user_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_series_purchases_guest_series "
        "ON series_purchases (guest_id, series_id) WHERE guest_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_content_free_published_episodes
        ON content (series_id, season_number, episode_number)
        WHERE type = 'episode' AND is_free = true AND is_published = true
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_content_genres_gin "
        "ON content USING GIN (genres)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_series_genres_gin "
        "ON series USING GIN (genres)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_series_genres_gin")
    op.execute("DROP INDEX IF EXISTS ix_content_genres_gin")
    op.execute("DROP INDEX IF EXISTS ix_content_free_published_episodes")
    op.execute("DROP INDEX IF EXISTS ix_series_purchases_guest_series")
    op.execute("DROP INDEX IF EXISTS ix_series_purchases_user_series")
    op.execute("DROP INDEX IF EXISTS ix_purchases_guest_content")
    op.execute("DROP INDEX IF EXISTS ix_payment_intents_plan_code")
    op.execute("ALTER TABLE payment_intents DROP COLUMN IF EXISTS plan_code")
