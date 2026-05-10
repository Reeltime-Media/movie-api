"""Initial schema — all tables

Revision ID: 0001
Revises:
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── users ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE users (
          id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          email         CITEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          full_name     TEXT,
          role          TEXT NOT NULL DEFAULT 'user'
                        CHECK (role IN ('user','admin')),
          is_active     BOOLEAN NOT NULL DEFAULT true,
          created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ── series ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE series (
          id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          slug              TEXT UNIQUE NOT NULL,
          title             TEXT NOT NULL,
          description       TEXT,
          poster_key        TEXT,
          monthly_price_usd NUMERIC(10,2) NOT NULL,
          is_published      BOOLEAN NOT NULL DEFAULT false,
          created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ── content ───────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE content (
          id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          type             TEXT NOT NULL CHECK (type IN ('single','episode')),
          series_id        UUID REFERENCES series(id) ON DELETE CASCADE,
          season_number    INT,
          episode_number   INT,
          slug             TEXT UNIQUE NOT NULL,
          title            TEXT NOT NULL,
          description      TEXT,
          duration_seconds INT,
          poster_key       TEXT,
          hls_master_key   TEXT,
          price_usd        NUMERIC(10,2),
          transcode_status TEXT NOT NULL DEFAULT 'pending'
                           CHECK (transcode_status IN ('pending','processing','ready','failed')),
          is_published     BOOLEAN NOT NULL DEFAULT false,
          search_vector    tsvector GENERATED ALWAYS AS
                           (to_tsvector('english',
                             coalesce(title,'') || ' ' || coalesce(description,'')))
                           STORED,
          created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT single_has_price CHECK (
            (type = 'single' AND price_usd IS NOT NULL AND series_id IS NULL) OR
            (type = 'episode' AND series_id IS NOT NULL AND price_usd IS NULL)
          )
        )
    """)
    op.execute("CREATE INDEX idx_content_search ON content USING GIN (search_vector)")
    op.execute("CREATE INDEX idx_content_series_id ON content (series_id)")

    # ── purchases ─────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE purchases (
          id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id         UUID NOT NULL REFERENCES users(id),
          content_id      UUID NOT NULL REFERENCES content(id),
          intent_id       TEXT NOT NULL UNIQUE,
          order_id        TEXT NOT NULL UNIQUE,
          bank            TEXT,
          amount_usd      NUMERIC(10,2) NOT NULL,
          purchased_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
          expires_at      TIMESTAMPTZ,
          first_played_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_purchases_user_id ON purchases (user_id)")

    # ── subscriptions ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE subscriptions (
          id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id              UUID NOT NULL REFERENCES users(id),
          plan                 TEXT NOT NULL DEFAULT 'series_monthly',
          status               TEXT NOT NULL DEFAULT 'active'
                               CHECK (status IN ('active','grace','expired')),
          current_period_start TIMESTAMPTZ NOT NULL,
          current_period_end   TIMESTAMPTZ NOT NULL,
          reminder_sent_at     TIMESTAMPTZ,
          created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_subscriptions_user_id ON subscriptions (user_id)")

    # ── subscription_payments ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE subscription_payments (
          id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          subscription_id   UUID NOT NULL REFERENCES subscriptions(id),
          intent_id         TEXT NOT NULL UNIQUE,
          order_id          TEXT NOT NULL UNIQUE,
          bank              TEXT,
          amount_usd        NUMERIC(10,2) NOT NULL,
          paid_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
          period_extended_to TIMESTAMPTZ NOT NULL
        )
    """)

    # ── watch_progress ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE watch_progress (
          user_id          UUID NOT NULL REFERENCES users(id),
          content_id       UUID NOT NULL REFERENCES content(id),
          position_seconds INT NOT NULL,
          completed        BOOLEAN NOT NULL DEFAULT false,
          last_watched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, content_id)
        )
    """)

    # ── payment_intents ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE payment_intents (
          intent_id  TEXT PRIMARY KEY,
          order_id   TEXT NOT NULL UNIQUE,
          user_id    UUID NOT NULL REFERENCES users(id),
          kind       TEXT NOT NULL CHECK (kind IN ('single','sub')),
          content_id UUID REFERENCES content(id),
          amount_usd NUMERIC(10,2) NOT NULL,
          status     TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','succeeded','failed','expired')),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ
        )
    """)

    # ── webhook_events ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE webhook_events (
          id           BIGSERIAL PRIMARY KEY,
          provider     TEXT NOT NULL,
          payload      JSONB NOT NULL,
          received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
          processed_at TIMESTAMPTZ,
          error        TEXT
        )
    """)

    # ── transcode_jobs ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE transcode_jobs (
          id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          content_id  UUID NOT NULL REFERENCES content(id),
          source_key  TEXT NOT NULL,
          status      TEXT NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued','running','success','failed')),
          attempts    INT NOT NULL DEFAULT 0,
          error       TEXT,
          started_at  TIMESTAMPTZ,
          finished_at TIMESTAMPTZ,
          created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_transcode_jobs_content_id ON transcode_jobs (content_id)")
    op.execute("CREATE INDEX idx_transcode_jobs_status ON transcode_jobs (status)")

    # ── updated_at auto-update trigger ────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    for tbl in ("users", "series", "content", "subscriptions"):
        op.execute(f"""
            CREATE TRIGGER trg_{tbl}_updated_at
            BEFORE UPDATE ON {tbl}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
        """)


def downgrade() -> None:
    for tbl in ("users", "series", "content", "subscriptions"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl}")

    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column")

    for tbl in (
        "transcode_jobs",
        "webhook_events",
        "payment_intents",
        "watch_progress",
        "subscription_payments",
        "subscriptions",
        "purchases",
        "content",
        "series",
        "users",
    ):
        op.execute(f"DROP TABLE IF EXISTS {tbl}")

    op.execute("DROP EXTENSION IF EXISTS citext")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
