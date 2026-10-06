"""Performance indexes, autovacuum tuning, and search path hardening

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Replace Bakong sweeper index with expression index matching COALESCE(bakong_qr_created_at, created_at)
    op.execute("DROP INDEX IF EXISTS ix_payment_intents_bakong_pending_sweep")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_payment_intents_bakong_pending_sweep_expr
        ON payment_intents (method, status, (COALESCE(bakong_qr_created_at, created_at)) ASC)
        WHERE status = 'pending' AND bakong_md5 IS NOT NULL
        """
    )

    # 2. Transcoder worker claim queue partial index
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_transcode_jobs_claim_queue
        ON transcode_jobs (status, created_at ASC)
        WHERE status = 'queued'
        """
    )

    # 3. Foreign key index on device pairing codes
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_device_pairing_codes_user_id
        ON device_pairing_codes (user_id)
        """
    )

    # 4. Watch progress recent list index
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_watch_progress_user_recent
        ON watch_progress (user_id, last_watched_at DESC, content_id)
        """
    )

    # 5. Active sessions lookup index
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_active_lookup
        ON sessions (id, expires_at)
        WHERE revoked_at IS NULL
        """
    )

    # 6. Hardened search_path for tsvector helper
    op.execute(
        "ALTER FUNCTION public.reeltime_simple_tsvector(text) SET search_path = public, pg_temp"
    )

    # 7. Autovacuum storage tuning for high-churn small tables
    op.execute(
        "ALTER TABLE public.transcode_jobs SET (autovacuum_vacuum_threshold = 10, autovacuum_vacuum_scale_factor = 0.05)"
    )
    op.execute(
        "ALTER TABLE public.payment_intents SET (autovacuum_vacuum_threshold = 10, autovacuum_vacuum_scale_factor = 0.05)"
    )
    op.execute(
        "ALTER TABLE public.sessions SET (autovacuum_vacuum_threshold = 10, autovacuum_vacuum_scale_factor = 0.05)"
    )
    op.execute(
        "ALTER TABLE public.series SET (autovacuum_vacuum_threshold = 10, autovacuum_vacuum_scale_factor = 0.05)"
    )
    op.execute(
        "ALTER TABLE public.tv_channels SET (autovacuum_vacuum_threshold = 10, autovacuum_vacuum_scale_factor = 0.05)"
    )

    # 8. Add 'superseded' to payment_intents status check constraint
    op.execute("ALTER TABLE payment_intents DROP CONSTRAINT IF EXISTS payment_intents_status_check")
    op.execute(
        """
        ALTER TABLE payment_intents ADD CONSTRAINT payment_intents_status_check 
        CHECK (status IN ('pending', 'succeeded', 'failed', 'expired', 'superseded'))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sessions_active_lookup")
    op.execute("DROP INDEX IF EXISTS idx_watch_progress_user_recent")
    op.execute("DROP INDEX IF EXISTS idx_device_pairing_codes_user_id")
    op.execute("DROP INDEX IF EXISTS idx_transcode_jobs_claim_queue")
    op.execute("DROP INDEX IF EXISTS ix_payment_intents_bakong_pending_sweep_expr")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_payment_intents_bakong_pending_sweep
        ON payment_intents (method, status, bakong_qr_created_at)
        WHERE status = 'pending' AND bakong_md5 IS NOT NULL
        """
    )
