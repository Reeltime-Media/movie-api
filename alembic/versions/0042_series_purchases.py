"""Series unlock — one-time per-series purchase (separate from subscription)

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-08

Adds a `series_purchases` table (mirrors `purchases`, but keyed on series_id
instead of content_id) plus a nullable `series_id` FK on `payment_intents`
and a new 'series' payment kind, so the Bakong "unlock this series" flow can
track its own pending intents distinctly from movie purchases and
subscriptions.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KIND_CONSTRAINT = "payment_intents_kind_check"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS series_purchases (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID REFERENCES users(id) ON DELETE CASCADE,
            guest_id     TEXT,
            series_id    UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
            intent_id    TEXT NOT NULL UNIQUE,
            order_id     TEXT NOT NULL UNIQUE,
            bank         TEXT,
            amount_usd   NUMERIC(10,2) NOT NULL,
            purchased_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_series_purchases_user_id ON series_purchases(user_id);
        CREATE INDEX IF NOT EXISTS idx_series_purchases_guest_id ON series_purchases(guest_id);
        CREATE INDEX IF NOT EXISTS idx_series_purchases_series_id ON series_purchases(series_id);
        """
    )
    op.execute("ALTER TABLE series_purchases ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON series_purchases FROM anon, authenticated")
    op.execute("GRANT ALL ON TABLE series_purchases TO service_role")
    op.execute(
        """
        DROP POLICY IF EXISTS no_direct_client_access ON public.series_purchases;
        CREATE POLICY no_direct_client_access ON public.series_purchases
          FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
        """
    )

    op.execute(
        "ALTER TABLE payment_intents ADD COLUMN IF NOT EXISTS series_id "
        "UUID REFERENCES series(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_intents_series_id "
        "ON payment_intents(series_id)"
    )
    op.execute(f"ALTER TABLE payment_intents DROP CONSTRAINT IF EXISTS {_KIND_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE payment_intents ADD CONSTRAINT {_KIND_CONSTRAINT} "
        "CHECK (kind IN ('single', 'sub', 'series'))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE payment_intents DROP CONSTRAINT IF EXISTS {_KIND_CONSTRAINT}")
    op.execute("DELETE FROM payment_intents WHERE kind = 'series'")
    op.execute(
        f"ALTER TABLE payment_intents ADD CONSTRAINT {_KIND_CONSTRAINT} "
        "CHECK (kind IN ('single', 'sub'))"
    )
    op.execute("ALTER TABLE payment_intents DROP COLUMN IF EXISTS series_id")
    op.execute("DROP TABLE IF EXISTS series_purchases;")
