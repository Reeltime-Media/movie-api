"""transcode_jobs: cascade delete when content is deleted

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("transcode_jobs_content_id_fkey", "transcode_jobs", type_="foreignkey")
    op.create_foreign_key(
        "transcode_jobs_content_id_fkey",
        "transcode_jobs", "content",
        ["content_id"], ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("transcode_jobs_content_id_fkey", "transcode_jobs", type_="foreignkey")
    op.create_foreign_key(
        "transcode_jobs_content_id_fkey",
        "transcode_jobs", "content",
        ["content_id"], ["id"],
    )
