"""Add ratings table for user movie star ratings

Revision ID: 0039
Revises: 0038a
Create Date: 2026-08-19

One row per (user, movie), 1-5 stars. content.rating is recomputed as the
live average (mapped onto the existing 0-10 display scale) whenever a rating
is written, so the aggregate shown on the watch page becomes real once any
user has rated a movie.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0039"
down_revision: Union[str, None] = "0038a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ratings (
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content_id  UUID NOT NULL REFERENCES content(id) ON DELETE CASCADE,
            value       SMALLINT NOT NULL CHECK (value BETWEEN 1 AND 5),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, content_id)
        );
        CREATE INDEX idx_ratings_content_id ON ratings(content_id);
        """
    )
    op.execute("ALTER TABLE ratings ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON ratings FROM anon, authenticated")
    op.execute("GRANT ALL ON TABLE ratings TO service_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ratings;")
