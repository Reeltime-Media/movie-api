"""Enable RLS on newer public tables flagged by Supabase linter

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-11

Same approach as 0009: FastAPI uses the postgres/pooler role, not PostgREST.
Enable RLS with no anon/authenticated policies so the Data API cannot read these tables.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = (
    "password_reset_tokens",
    "favorites",
    "sessions",
    "genres",
)


def upgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            REVOKE ALL ON TABLE public.{table} FROM anon, authenticated;
            GRANT ALL ON TABLE public.{table} TO service_role;
            """
        )


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(
            f"""
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table}
              TO anon, authenticated;
            """
        )
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
