"""Add title_km to content and series; split combined bilingual titles.

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-18

Stores Khmer titles separately from English `title`. Existing rows whose
`title` looks like "Khmer - English" are split in place.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safety net if 0030 ran an older revision that dropped method's DEFAULT.
    op.execute(
        "ALTER TABLE payment_intents ALTER COLUMN method SET DEFAULT 'baray'"
    )

    op.execute("ALTER TABLE content ADD COLUMN IF NOT EXISTS title_km TEXT")
    op.execute("ALTER TABLE series ADD COLUMN IF NOT EXISTS title_km TEXT")

    # Split "Khmer - English" titles where the left side has Khmer letters
    # (U+1780–U+17FF = chr 6016–6143).
    op.execute(
        """
        UPDATE content
        SET
          title_km = TRIM(SPLIT_PART(title, ' - ', 1)),
          title = TRIM(SUBSTRING(title FROM POSITION(' - ' IN title) + 3))
        WHERE title_km IS NULL
          AND POSITION(' - ' IN title) > 0
          AND TRIM(SPLIT_PART(title, ' - ', 1)) ~ ('[' || chr(6016) || '-' || chr(6143) || ']')
          AND TRIM(SUBSTRING(title FROM POSITION(' - ' IN title) + 3)) <> ''
        """
    )
    op.execute(
        """
        UPDATE series
        SET
          title_km = TRIM(SPLIT_PART(title, ' - ', 1)),
          title = TRIM(SUBSTRING(title FROM POSITION(' - ' IN title) + 3))
        WHERE title_km IS NULL
          AND POSITION(' - ' IN title) > 0
          AND TRIM(SPLIT_PART(title, ' - ', 1)) ~ ('[' || chr(6016) || '-' || chr(6143) || ']')
          AND TRIM(SUBSTRING(title FROM POSITION(' - ' IN title) + 3)) <> ''
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE content
        SET title = title_km || ' - ' || title
        WHERE title_km IS NOT NULL AND TRIM(title_km) <> ''
        """
    )
    op.execute(
        """
        UPDATE series
        SET title = title_km || ' - ' || title
        WHERE title_km IS NOT NULL AND TRIM(title_km) <> ''
        """
    )
    op.execute("ALTER TABLE content DROP COLUMN IF EXISTS title_km")
    op.execute("ALTER TABLE series DROP COLUMN IF EXISTS title_km")
