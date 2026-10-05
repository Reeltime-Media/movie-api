"""Atomic session/checkout safeguards

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-05

- Snapshot subscription billing interval on payment_intents
- Unique pending Bakong intents per buyer+product/plan
- One subscription row per user (dedupe then constrain)
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payment_intents "
        "ADD COLUMN IF NOT EXISTS plan_interval_days INTEGER"
    )

    op.execute(
        """
        UPDATE payment_intents AS pi
        SET plan_interval_days = sp.billing_interval_days
        FROM subscription_plans AS sp
        WHERE pi.kind = 'sub'
          AND pi.plan_code IS NOT NULL
          AND pi.plan_code = sp.code
          AND pi.plan_interval_days IS NULL
        """
    )

    # Point payments at the surviving subscription per user before deleting dupes.
    op.execute(
        """
        WITH ranked AS (
          SELECT
            id,
            user_id,
            ROW_NUMBER() OVER (
              PARTITION BY user_id
              ORDER BY current_period_end DESC, created_at DESC, id DESC
            ) AS rn
          FROM subscriptions
        ),
        keepers AS (
          SELECT id, user_id FROM ranked WHERE rn = 1
        )
        UPDATE subscription_payments sp
        SET subscription_id = k.id
        FROM subscriptions doomed
        JOIN keepers k ON k.user_id = doomed.user_id
        WHERE sp.subscription_id = doomed.id
          AND doomed.id <> k.id
        """
    )
    op.execute(
        """
        WITH ranked AS (
          SELECT
            id,
            ROW_NUMBER() OVER (
              PARTITION BY user_id
              ORDER BY current_period_end DESC, created_at DESC, id DESC
            ) AS rn
          FROM subscriptions
        )
        DELETE FROM subscriptions
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_subscriptions_user_id'
          ) THEN
            ALTER TABLE subscriptions
              ADD CONSTRAINT uq_subscriptions_user_id UNIQUE (user_id);
          END IF;
        END $$;
        """
    )

    # Collapse duplicate pending rows so unique indexes can be created.
    for sql in (
        """
        DELETE FROM payment_intents a
        USING payment_intents b
        WHERE a.ctid < b.ctid
          AND a.status = 'pending' AND b.status = 'pending'
          AND a.method = 'bakong' AND b.method = 'bakong'
          AND a.kind = 'single' AND b.kind = 'single'
          AND a.user_id IS NOT NULL AND a.user_id = b.user_id
          AND a.content_id IS NOT NULL AND a.content_id = b.content_id
        """,
        """
        DELETE FROM payment_intents a
        USING payment_intents b
        WHERE a.ctid < b.ctid
          AND a.status = 'pending' AND b.status = 'pending'
          AND a.method = 'bakong' AND b.method = 'bakong'
          AND a.kind = 'single' AND b.kind = 'single'
          AND a.guest_id IS NOT NULL AND a.guest_id = b.guest_id
          AND a.content_id IS NOT NULL AND a.content_id = b.content_id
        """,
        """
        DELETE FROM payment_intents a
        USING payment_intents b
        WHERE a.ctid < b.ctid
          AND a.status = 'pending' AND b.status = 'pending'
          AND a.method = 'bakong' AND b.method = 'bakong'
          AND a.kind = 'series' AND b.kind = 'series'
          AND a.user_id IS NOT NULL AND a.user_id = b.user_id
          AND a.series_id IS NOT NULL AND a.series_id = b.series_id
        """,
        """
        DELETE FROM payment_intents a
        USING payment_intents b
        WHERE a.ctid < b.ctid
          AND a.status = 'pending' AND b.status = 'pending'
          AND a.method = 'bakong' AND b.method = 'bakong'
          AND a.kind = 'series' AND b.kind = 'series'
          AND a.guest_id IS NOT NULL AND a.guest_id = b.guest_id
          AND a.series_id IS NOT NULL AND a.series_id = b.series_id
        """,
        """
        DELETE FROM payment_intents a
        USING payment_intents b
        WHERE a.ctid < b.ctid
          AND a.status = 'pending' AND b.status = 'pending'
          AND a.method = 'bakong' AND b.method = 'bakong'
          AND a.kind = 'sub' AND b.kind = 'sub'
          AND a.user_id IS NOT NULL AND a.user_id = b.user_id
          AND a.plan_code IS NOT NULL AND a.plan_code = b.plan_code
        """,
    ):
        op.execute(sql)

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_bakong_movie_user
        ON payment_intents (user_id, content_id)
        WHERE status = 'pending'
          AND method = 'bakong'
          AND kind = 'single'
          AND user_id IS NOT NULL
          AND content_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_bakong_movie_guest
        ON payment_intents (guest_id, content_id)
        WHERE status = 'pending'
          AND method = 'bakong'
          AND kind = 'single'
          AND guest_id IS NOT NULL
          AND content_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_bakong_series_user
        ON payment_intents (user_id, series_id)
        WHERE status = 'pending'
          AND method = 'bakong'
          AND kind = 'series'
          AND user_id IS NOT NULL
          AND series_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_bakong_series_guest
        ON payment_intents (guest_id, series_id)
        WHERE status = 'pending'
          AND method = 'bakong'
          AND kind = 'series'
          AND guest_id IS NOT NULL
          AND series_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_bakong_sub_user_plan
        ON payment_intents (user_id, plan_code)
        WHERE status = 'pending'
          AND method = 'bakong'
          AND kind = 'sub'
          AND user_id IS NOT NULL
          AND plan_code IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_pending_bakong_sub_user_plan")
    op.execute("DROP INDEX IF EXISTS uq_pending_bakong_series_guest")
    op.execute("DROP INDEX IF EXISTS uq_pending_bakong_series_user")
    op.execute("DROP INDEX IF EXISTS uq_pending_bakong_movie_guest")
    op.execute("DROP INDEX IF EXISTS uq_pending_bakong_movie_user")
    op.execute(
        "ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS uq_subscriptions_user_id"
    )
    op.execute(
        "ALTER TABLE payment_intents DROP COLUMN IF EXISTS plan_interval_days"
    )
