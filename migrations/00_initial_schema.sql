-- ═══════════════════════════════════════════════════════════════════════════════
-- Reeltime — Initial Schema
-- Run once in: Supabase Dashboard → SQL Editor
-- ═══════════════════════════════════════════════════════════════════════════════

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "citext";     -- case-insensitive email uniqueness

-- ── users ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email        CITEXT      NOT NULL UNIQUE,
    password_hash TEXT       NOT NULL,
    full_name    TEXT,
    role         TEXT        NOT NULL DEFAULT 'user',  -- 'user' | 'admin'
    is_active    BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── series ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS series (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    slug              TEXT        NOT NULL UNIQUE,
    title             TEXT        NOT NULL,
    description       TEXT,
    genres            TEXT[]      NOT NULL DEFAULT '{}',
    release_year      INTEGER,
    rating            NUMERIC(3,1),
    poster_key        TEXT,
    monthly_price_usd NUMERIC(10,2) NOT NULL,
    is_published      BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── content ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    type             TEXT        NOT NULL CHECK (type IN ('single', 'episode')),
    series_id        UUID        REFERENCES series (id) ON DELETE CASCADE,
    season_number    INTEGER,
    episode_number   INTEGER,
    slug             TEXT        NOT NULL UNIQUE,
    title            TEXT        NOT NULL,
    description      TEXT,
    genres           TEXT[]      NOT NULL DEFAULT '{}',
    release_year     INTEGER,
    rating           NUMERIC(3,1),
    runtime          TEXT,
    duration_seconds INTEGER,
    poster_key       TEXT,
    trailer_url      TEXT,
    hls_master_key   TEXT,
    price_usd        NUMERIC(10,2),
    status           TEXT        NOT NULL DEFAULT 'draft'
                                 CHECK (status IN ('draft','review','scheduled','published')),
    is_published     BOOLEAN     NOT NULL DEFAULT FALSE,
    transcode_status TEXT        NOT NULL DEFAULT 'pending',
    search_vector    TSVECTOR
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(title,'') || ' ' || coalesce(description,''))
        ) STORED,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Episodes must belong to a series; singles must not
    CONSTRAINT chk_episode_requires_series
        CHECK (type = 'single' OR series_id IS NOT NULL),
    CONSTRAINT chk_single_no_series
        CHECK (type = 'episode' OR series_id IS NULL),
    -- Episodes require season + episode numbers
    CONSTRAINT chk_episode_numbers
        CHECK (type = 'single' OR (season_number IS NOT NULL AND episode_number IS NOT NULL)),
    -- Singles require a price; episodes must not have one
    CONSTRAINT chk_single_has_price
        CHECK (type = 'episode' OR price_usd IS NOT NULL),
    CONSTRAINT chk_episode_no_price
        CHECK (type = 'single' OR price_usd IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_content_series_id     ON content (series_id);
CREATE INDEX IF NOT EXISTS idx_content_search_vector ON content USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_content_status        ON content (status);

-- ── transcode_jobs ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transcode_jobs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id  UUID        NOT NULL REFERENCES content (id) ON DELETE CASCADE,
    source_key  TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'queued',  -- queued|running|success|failed
    attempts    INTEGER     NOT NULL DEFAULT 0,
    error       TEXT,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transcode_jobs_status ON transcode_jobs (status, created_at);

-- ── subscriptions ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID        NOT NULL REFERENCES users (id),
    plan                 TEXT        NOT NULL DEFAULT 'series_monthly',
    status               TEXT        NOT NULL DEFAULT 'active',  -- active|cancelled|expired
    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end   TIMESTAMPTZ NOT NULL,
    reminder_sent_at     TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions (user_id);

-- ── subscription_payments ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscription_payments (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id     UUID        NOT NULL REFERENCES subscriptions (id),
    intent_id           TEXT        NOT NULL UNIQUE,
    order_id            TEXT        NOT NULL UNIQUE,
    bank                TEXT,
    amount_usd          NUMERIC(10,2) NOT NULL,
    paid_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    period_extended_to  TIMESTAMPTZ NOT NULL
);

-- ── purchases ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS purchases (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID        NOT NULL REFERENCES users (id),
    content_id     UUID        NOT NULL REFERENCES content (id),
    intent_id      TEXT        NOT NULL UNIQUE,
    order_id       TEXT        NOT NULL UNIQUE,
    bank           TEXT,
    amount_usd     NUMERIC(10,2) NOT NULL,
    purchased_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ,
    first_played_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_purchases_user_id    ON purchases (user_id);
CREATE INDEX IF NOT EXISTS idx_purchases_content_id ON purchases (content_id);

-- ── payment_intents ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payment_intents (
    intent_id   TEXT        PRIMARY KEY,
    order_id    TEXT        NOT NULL UNIQUE,
    user_id     UUID        NOT NULL REFERENCES users (id),
    kind        TEXT        NOT NULL,  -- 'single' | 'sub'
    content_id  UUID        REFERENCES content (id),
    amount_usd  NUMERIC(10,2) NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending',  -- pending|paid|failed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payment_intents_user_id ON payment_intents (user_id);

-- ── watch_progress ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS watch_progress (
    user_id          UUID    NOT NULL REFERENCES users (id),
    content_id       UUID    NOT NULL REFERENCES content (id),
    position_seconds INTEGER NOT NULL,
    completed        BOOLEAN NOT NULL DEFAULT FALSE,
    last_watched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, content_id)
);

-- ── webhook_events ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhook_events (
    id           BIGSERIAL   PRIMARY KEY,
    provider     TEXT        NOT NULL,
    payload      JSONB       NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    error        TEXT
);

-- ── updated_at triggers ───────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DO $$ BEGIN
    CREATE TRIGGER trg_users_updated_at
        BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_series_updated_at
        BEFORE UPDATE ON series
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_content_updated_at
        BEFORE UPDATE ON content
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_subscriptions_updated_at
        BEFORE UPDATE ON subscriptions
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ── is_published sync trigger ─────────────────────────────────────────────────
-- Keeps is_published in sync with status automatically at the DB level
CREATE OR REPLACE FUNCTION sync_is_published()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.is_published = (NEW.status = 'published');
    RETURN NEW;
END;
$$;

DO $$ BEGIN
    CREATE TRIGGER trg_content_sync_published
        BEFORE INSERT OR UPDATE OF status ON content
        FOR EACH ROW EXECUTE FUNCTION sync_is_published();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
