"""Bakong KHQR inline checkout — method + bakong_md5 on payment_intents

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-18

Bakong has no webhook — we poll `check_transaction_by_md5` ourselves, keyed by
the md5 of the generated KHQR string. `method` distinguishes which provider an
intent belongs to; existing rows backfill to 'baray' (the only provider until now).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_intents",
        sa.Column("method", sa.Text(), nullable=False, server_default="baray"),
    )
    op.alter_column("payment_intents", "method", server_default=None)
    op.add_column("payment_intents", sa.Column("bakong_md5", sa.Text(), nullable=True))
    # The generated KHQR string embeds a creation timestamp, so it can't be
    # deterministically re-derived later — persist it verbatim to redisplay
    # the exact same QR (and matching md5) on a repeat "pending intent" fetch.
    op.add_column("payment_intents", sa.Column("bakong_qr", sa.Text(), nullable=True))
    op.create_index(
        "ix_payment_intents_bakong_md5",
        "payment_intents",
        ["bakong_md5"],
        unique=True,
        postgresql_where=sa.text("bakong_md5 IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_payment_intents_bakong_md5", table_name="payment_intents")
    op.drop_column("payment_intents", "bakong_qr")
    op.drop_column("payment_intents", "bakong_md5")
    op.drop_column("payment_intents", "method")
