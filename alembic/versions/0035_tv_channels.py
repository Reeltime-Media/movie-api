"""Add tv_channels table for live TV restream channels

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-08

Channel metadata + live state for the FFmpeg-source -> HLS-origin -> CDN
restream pipeline. The actual restream process runs in a separate live
service (LIVE_SERVICE_URL); this table just tracks each channel's source,
its current live HLS output URL, and status.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tv_channels (
            id UUID PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            logo_key TEXT,
            source_url TEXT NOT NULL,
            hls_playback_url TEXT,
            status TEXT NOT NULL DEFAULT 'offline',
            status_error TEXT,
            is_published BOOLEAN NOT NULL DEFAULT false,
            is_free BOOLEAN NOT NULL DEFAULT false,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tv_channels_published "
        "ON tv_channels (is_published, sort_order)"
    )
    op.execute("ALTER TABLE public.tv_channels ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        REVOKE ALL ON TABLE public.tv_channels FROM anon, authenticated;
        GRANT ALL ON TABLE public.tv_channels TO service_role;
        """
    )
    op.execute(
        """
        DROP POLICY IF EXISTS no_direct_client_access ON public.tv_channels;
        CREATE POLICY no_direct_client_access ON public.tv_channels
          FOR ALL
          TO anon, authenticated
          USING (false)
          WITH CHECK (false);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tv_channels")
