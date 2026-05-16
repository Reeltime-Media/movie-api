-- Run this in Supabase Dashboard → SQL Editor

-- ── content table ─────────────────────────────────────────────────────────────
ALTER TABLE content
  ADD COLUMN IF NOT EXISTS genres       TEXT[]       NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS release_year INTEGER,
  ADD COLUMN IF NOT EXISTS rating       NUMERIC(3,1),
  ADD COLUMN IF NOT EXISTS runtime      TEXT,
  ADD COLUMN IF NOT EXISTS status       TEXT         NOT NULL DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS trailer_url  TEXT;

-- Backfill status from the existing is_published flag
UPDATE content
SET status = CASE WHEN is_published THEN 'published' ELSE 'draft' END
WHERE status = 'draft';

-- ── series table ──────────────────────────────────────────────────────────────
ALTER TABLE series
  ADD COLUMN IF NOT EXISTS genres       TEXT[]       NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS release_year INTEGER,
  ADD COLUMN IF NOT EXISTS rating       NUMERIC(3,1);
