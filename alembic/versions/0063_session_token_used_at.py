"""Record when a session's newest token first reaches the server

Revision ID: 0063
Revises: 0062
Create Date: 2026-11-13

token_used_at is set by the first request carrying the session's current
token_version and cleared by every refresh. A refresh with the replaced token
while it is still null means the device lost the refresh response, not that
the token was copied, so the session is kept instead of revoked. Existing
sessions start null, which only makes them more forgiving. Idempotent, like
the other recent migrations.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0063"
down_revision: Union[str, None] = "0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS token_used_at TIMESTAMPTZ NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS token_used_at")
