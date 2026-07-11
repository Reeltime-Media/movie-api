"""Add explicit deny policies for PostgREST client roles

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-11

RLS is intentionally enabled with no client access (FastAPI uses postgres/pooler).
Supabase linter rls_enabled_no_policy wants at least one policy — add deny-all
policies for anon/authenticated so intent is explicit and the advisor is quiet.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_POLICY = "no_direct_client_access"

_TABLES = (
    "alembic_version",
    "comment_reports",
    "comment_votes",
    "comments",
    "content",
    "favorites",
    "genres",
    "hero_featured_items",
    "password_reset_tokens",
    "payment_intents",
    "promotion_banners",
    "purchases",
    "series",
    "sessions",
    "subscription_payments",
    "subscription_plans",
    "subscriptions",
    "transcode_jobs",
    "users",
    "watch_progress",
    "webhook_events",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            DROP POLICY IF EXISTS {_POLICY} ON public.{table};
            CREATE POLICY {_POLICY} ON public.{table}
              FOR ALL
              TO anon, authenticated
              USING (false)
              WITH CHECK (false);
            """
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON public.{table}")
