"""Make the first 3 episodes of every series free (catalog-wide preview)

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-08

One-time data fix, not a schema change: for every published episode, ranks
by (season_number, episode_number) within its series and sets is_free=true
for the first 3. Only ever flips false -> true — an episode already free
(a handful of series already did this ad hoc, with 2 free episodes) is left
alone, so nothing already free becomes paid.

This does not affect new episodes uploaded later — a future upload isn't
retroactively made free just because it lands in an series' first 3 slots.
That would need an app-level rule (e.g. in the episode-upload flow), which
is a separate change from this one-time catalog fix.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FREE_EPISODE_COUNT = 3


def upgrade() -> None:
    op.execute(
        f"""
        WITH ranked AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY series_id
                ORDER BY season_number NULLS LAST, episode_number NULLS LAST
            ) AS rn
            FROM content
            WHERE type = 'episode' AND is_published = true
        )
        UPDATE content SET is_free = true
        WHERE id IN (SELECT id FROM ranked WHERE rn <= {_FREE_EPISODE_COUNT})
          AND is_free = false
        """
    )


def downgrade() -> None:
    # Data fix, not schema — no reliable way to know which of these rows were
    # free before this ran (the pre-existing 2-episode-free series would
    # incorrectly get un-freed too). Not reversible; re-run 0043's data check
    # manually against a backup if you need the prior state.
    pass
