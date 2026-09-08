"""Flag certain series as "short movies" for the /short-movies catalog page

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-08

Adds `is_short_movie` (bool, default false) to `series` — additive and
orthogonal to everything else on the row, so flagged series keep working
exactly as any other series (subscription gating, per-series unlock,
episodes, playback) and additionally surface on /short-movies.

Also flags the specific series the catalog team identified as short-form
by slug. Three titles on their list ("The Cub Who Bought The World",
"Divorce is Invincible", "Treasure Appraisal Genius") have no matching row
in `series` as of this migration — content hasn't been imported yet, so
they're intentionally left out here.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SHORT_MOVIE_SLUGS = [
    "live-streaming-in-the-spirit-realm-2024",
    "dual-travel-ultimate-fortune-or-double-dimension-tycoon-2025",
    "wow-the-ancient-imperial-concubine-traveled-through-time-and-space-to-my-home-or-help-my-harem-traveled-to-modern-times-2024",
    "the-gifted-quadruplets-2024",
    "my-connections-span-three-realms-2025",
    "i-crafted-the-ancient-xuanyuan-sword-2025",
    "i-can-hear-the-voices-of-animals-2024",
]


def upgrade() -> None:
    op.execute(
        "ALTER TABLE series ADD COLUMN IF NOT EXISTS is_short_movie "
        "BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_series_is_short_movie "
        "ON series(is_short_movie) WHERE is_short_movie"
    )
    slugs_sql = ", ".join(f"'{slug}'" for slug in _SHORT_MOVIE_SLUGS)
    op.execute(f"UPDATE series SET is_short_movie = true WHERE slug IN ({slugs_sql})")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_series_is_short_movie")
    op.execute("ALTER TABLE series DROP COLUMN IF EXISTS is_short_movie")
