"""Google OAuth fields on users

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_id", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
    op.drop_index("ix_users_google_id", table_name="users")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "google_id")
