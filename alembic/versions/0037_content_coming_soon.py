"""Add release_at column to content for Coming Soon scheduling

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-18

Adds a nullable release_at timestamp used by the "Coming Soon" admin
feature: an announced release date/time for a not-yet-published movie.
When set and the movie's video is ready, the in-process sweeper
(app/services/coming_soon_sweeper.py) flips status to 'published' once
release_at has passed. Content.status also gains a new 'coming_soon'
value (app-level only — status has no DB check constraint).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE content ADD COLUMN IF NOT EXISTS release_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE content DROP COLUMN IF EXISTS release_at")
