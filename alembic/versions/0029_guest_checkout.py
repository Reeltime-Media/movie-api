"""Guest checkout — nullable user_id + guest_id on payment_intents/purchases

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-18

Lets an unauthenticated buyer purchase a movie: the intent/purchase row is
keyed by an anonymous `guest_id` cookie token instead of `user_id`. Same shape
as 0008_user_google_auth making `users.password_hash` nullable for a second
auth path.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("payment_intents", "user_id", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("payment_intents", sa.Column("guest_id", sa.Text(), nullable=True))
    op.create_index("ix_payment_intents_guest_id", "payment_intents", ["guest_id"])

    op.alter_column("purchases", "user_id", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("purchases", sa.Column("guest_id", sa.Text(), nullable=True))
    op.create_index("ix_purchases_guest_id", "purchases", ["guest_id"])


def downgrade() -> None:
    op.drop_index("ix_purchases_guest_id", table_name="purchases")
    op.drop_column("purchases", "guest_id")
    op.alter_column("purchases", "user_id", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=False)

    op.drop_index("ix_payment_intents_guest_id", table_name="payment_intents")
    op.drop_column("payment_intents", "guest_id")
    op.alter_column("payment_intents", "user_id", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=False)
