"""Add genres table with seeded built-in genres

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_GENRES = [
    "Action", "Adventure", "Animation", "Biography", "Comedy",
    "Crime", "Documentary", "Drama", "Family", "Fantasy",
    "History", "Horror", "Music", "Mystery", "Romance",
    "Sci-Fi", "Sport", "Thriller", "War", "Western",
]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS genres (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    for genre in _SEED_GENRES:
        op.execute(
            f"INSERT INTO genres (name) VALUES ('{genre}') "
            "ON CONFLICT (name) DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS genres")
