"""Bilingual search_vector + pg_trgm indexes for catalog search

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-18

Restores a stored tsvector (dropped in 0020) that includes English title,
Khmer title_km, and description. Uses the 'simple' text search config so
Khmer tokens are not stemmed as English. Genres stay on the ILIKE path
(array_to_string is not immutable, so it cannot live in a generated column).

Also enables pg_trgm and GIN trigram indexes so ILIKE '%term%' substring
search can use indexes on title / title_km.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONTENT_VECTOR = """
to_tsvector(
  'simple',
  coalesce(title, '') || ' ' ||
  coalesce(title_km, '') || ' ' ||
  coalesce(description, '')
)
"""

_SERIES_VECTOR = """
to_tsvector(
  'simple',
  coalesce(title, '') || ' ' ||
  coalesce(title_km, '') || ' ' ||
  coalesce(description, '')
)
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute("DROP INDEX IF EXISTS idx_content_search")
    op.execute("ALTER TABLE content DROP COLUMN IF EXISTS search_vector")
    op.execute(
        f"""
        ALTER TABLE content
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS ({_CONTENT_VECTOR}) STORED
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_search ON content USING GIN (search_vector)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_title_trgm "
        "ON content USING GIN (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_title_km_trgm "
        "ON content USING GIN (title_km gin_trgm_ops)"
    )

    op.execute("DROP INDEX IF EXISTS idx_series_search")
    op.execute("ALTER TABLE series DROP COLUMN IF EXISTS search_vector")
    op.execute(
        f"""
        ALTER TABLE series
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS ({_SERIES_VECTOR}) STORED
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_series_search ON series USING GIN (search_vector)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_series_title_trgm "
        "ON series USING GIN (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_series_title_km_trgm "
        "ON series USING GIN (title_km gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_content_title_km_trgm")
    op.execute("DROP INDEX IF EXISTS idx_content_title_trgm")
    op.execute("DROP INDEX IF EXISTS idx_content_search")
    op.execute("ALTER TABLE content DROP COLUMN IF EXISTS search_vector")

    op.execute("DROP INDEX IF EXISTS idx_series_title_km_trgm")
    op.execute("DROP INDEX IF EXISTS idx_series_title_trgm")
    op.execute("DROP INDEX IF EXISTS idx_series_search")
    op.execute("ALTER TABLE series DROP COLUMN IF EXISTS search_vector")
