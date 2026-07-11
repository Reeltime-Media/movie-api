"""Fix function search_path and move citext out of public

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-11

Addresses Supabase linter:
- function_search_path_mutable on update_updated_at_column
- extension_in_public for citext
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.update_updated_at_column()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $function$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $function$
        """
    )
    # Supabase provides an `extensions` schema for non-public extensions.
    op.execute("CREATE SCHEMA IF NOT EXISTS extensions")
    op.execute("ALTER EXTENSION citext SET SCHEMA extensions")


def downgrade() -> None:
    op.execute("ALTER EXTENSION citext SET SCHEMA public")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.update_updated_at_column()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $function$
        """
    )
