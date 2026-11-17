"""PayPal checkout — order/capture ids on payment_intents, webhook event lookup index.

Revision ID: 0064
Revises: 0063
Create Date: 2026-11-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0064"
down_revision: Union[str, None] = "0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE payment_intents ADD COLUMN IF NOT EXISTS paypal_order_id TEXT")
    op.execute("ALTER TABLE payment_intents ADD COLUMN IF NOT EXISTS paypal_capture_id TEXT")
    # One PayPal order belongs to exactly one intent; the return page and the webhook
    # both look the intent up by it.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_intents_paypal_order_id
        ON payment_intents (paypal_order_id)
        WHERE paypal_order_id IS NOT NULL
        """
    )
    # PayPal re-delivers webhooks; the handler skips events it already processed.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_webhook_events_paypal_event_id
        ON webhook_events ((payload ->> 'id'))
        WHERE provider = 'paypal'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_webhook_events_paypal_event_id")
    op.execute("DROP INDEX IF EXISTS uq_payment_intents_paypal_order_id")
    op.execute("ALTER TABLE payment_intents DROP COLUMN IF EXISTS paypal_capture_id")
    op.execute("ALTER TABLE payment_intents DROP COLUMN IF EXISTS paypal_order_id")
