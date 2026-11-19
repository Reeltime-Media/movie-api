"""Scope content, series, plans and subscriptions by app; add Kun Khmer match details

Revision ID: 0066
Revises: 0065
Create Date: 2026-11-19

Every existing row becomes 'reeltime', so Reeltime keeps working unchanged.
Subscriptions move from one row per user to one row per user per app, so a TV5
plan never extends or replaces a Reeltime subscription. Idempotent.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0066"
down_revision: Union[str, None] = "0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_APP_TABLES = ("content", "series", "subscription_plans", "subscriptions")


def upgrade() -> None:
    for table in _APP_TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS app TEXT NOT NULL DEFAULT 'reeltime'"
        )
        op.execute(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{table}_app_check') THEN
                ALTER TABLE {table}
                  ADD CONSTRAINT {table}_app_check CHECK (app IN ('reeltime', 'tv5'));
              END IF;
            END $$;
            """
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_content_app_type ON content (app, type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_series_app ON series (app)")

    op.execute("ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS uq_subscriptions_user_id")
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_subscriptions_user_app') THEN
            ALTER TABLE subscriptions
              ADD CONSTRAINT uq_subscriptions_user_app UNIQUE (user_id, app);
          END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS match_details (
            content_id    UUID PRIMARY KEY REFERENCES content(id) ON DELETE CASCADE,
            red_fighter   TEXT NOT NULL,
            blue_fighter  TEXT NOT NULL,
            event_name    TEXT NULL,
            weight_class  TEXT NULL,
            match_date    DATE NULL,
            winner        TEXT NULL CHECK (winner IN ('red', 'blue', 'draw', 'no_contest')),
            result_method TEXT NULL,
            result_round  INTEGER NULL CHECK (result_round > 0),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE match_details ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON match_details FROM anon, authenticated")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON match_details TO service_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS match_details")
    op.execute("ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS uq_subscriptions_user_app")
    # Only restorable while every user has at most one subscription row.
    op.execute(
        "ALTER TABLE subscriptions ADD CONSTRAINT uq_subscriptions_user_id UNIQUE (user_id)"
    )
    op.execute("DROP INDEX IF EXISTS ix_series_app")
    op.execute("DROP INDEX IF EXISTS ix_content_app_type")
    for table in _APP_TABLES:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_app_check")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS app")
