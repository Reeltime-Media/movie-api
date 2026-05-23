"""Comment threads, votes, and reports

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comments",
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("comments.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_comments_parent_id", "comments", ["parent_id"])

    op.create_table(
        "comment_votes",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("comment_id", UUID(as_uuid=True), sa.ForeignKey("comments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "comment_id"),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_comment_votes_value"),
    )
    op.create_index("ix_comment_votes_comment_id", "comment_votes", ["comment_id"])

    op.create_table(
        "comment_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("comment_id", UUID(as_uuid=True), sa.ForeignKey("comments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_id", "comment_id", name="uq_comment_reports_user_comment"),
    )


def downgrade() -> None:
    op.drop_table("comment_reports")
    op.drop_index("ix_comment_votes_comment_id", table_name="comment_votes")
    op.drop_table("comment_votes")
    op.drop_index("ix_comments_parent_id", table_name="comments")
    op.drop_column("comments", "parent_id")
