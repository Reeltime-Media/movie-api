"""Enable RLS on public tables flagged by Supabase linter

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-24

Reeltime uses FastAPI + SQLAlchemy (postgres pooler), not PostgREST from the browser.
Enabling RLS with no anon/authenticated policies blocks direct Supabase Data API access
while the API service role / postgres user continues to work normally.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables reported by Supabase database linter (rls_disabled_in_public)
_RLS_TABLES = (
    "comments",
    "comment_votes",
    "comment_reports",
    "subscription_plans",
    "alembic_version",
)


def upgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    # Belt-and-suspenders: strip default PostgREST grants on app tables.
    # (alembic_version is internal; comments/subscription_plans are API-only.)
    for table in ("comments", "comment_votes", "comment_reports", "subscription_plans"):
        op.execute(
            f"""
            REVOKE ALL ON TABLE public.{table} FROM anon, authenticated;
            GRANT ALL ON TABLE public.{table} TO service_role;
            """
        )


def downgrade() -> None:
    for table in ("comments", "comment_votes", "comment_reports", "subscription_plans"):
        op.execute(
            f"""
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table}
              TO anon, authenticated;
            """
        )

    for table in reversed(_RLS_TABLES):
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
