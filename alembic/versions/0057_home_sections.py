"""Add home_sections + home_section_items for landing page builder

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-28

Admin-curated home layout: section order/titles/visibility and ordered
item refs (movies, series, TV channels, hero slides, banners).

Idempotent: tables may already exist if applied outside Alembic.
Seeds default sections and copies free_today / coming_soon / genre_rail rows.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS home_sections (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            type        TEXT NOT NULL,
            title       TEXT NULL,
            genre_name  TEXT NULL,
            is_visible  BOOLEAN NOT NULL DEFAULT true,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_home_sections_sort "
        "ON home_sections (sort_order, created_at DESC)"
    )
    op.execute("ALTER TABLE home_sections ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON home_sections FROM anon, authenticated")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON home_sections TO service_role"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS home_section_items (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            section_id  UUID NOT NULL REFERENCES home_sections(id) ON DELETE CASCADE,
            item_kind   TEXT NOT NULL,
            ref_id      UUID NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_home_section_item_ref UNIQUE (section_id, item_kind, ref_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_home_section_items_section_sort "
        "ON home_section_items (section_id, sort_order)"
    )
    op.execute("ALTER TABLE home_section_items ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON home_section_items FROM anon, authenticated")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON home_section_items TO service_role"
    )

    # Seed singleton sections only when the table is empty (fresh install / first migrate).
    op.execute(
        """
        INSERT INTO home_sections (id, type, title, genre_name, is_visible, sort_order)
        SELECT gen_random_uuid(), v.type, NULL, NULL, true, v.sort_order
        FROM (VALUES
            ('hero', 0),
            ('tv', 1),
            ('free_today', 2),
            ('most_watched', 3),
            ('plans', 4),
            ('coming_soon', 5),
            ('trending', 6),
            ('series', 7),
            ('banners', 8)
        ) AS v(type, sort_order)
        WHERE NOT EXISTS (SELECT 1 FROM home_sections LIMIT 1)
        """
    )

    # Copy free_today_items into the free_today section when that section has no items yet.
    op.execute(
        """
        INSERT INTO home_section_items (id, section_id, item_kind, ref_id, sort_order)
        SELECT gen_random_uuid(), s.id, 'movie', f.content_id, f.sort_order
        FROM home_sections s
        JOIN free_today_items f ON true
        WHERE s.type = 'free_today'
          AND NOT EXISTS (
            SELECT 1 FROM home_section_items i WHERE i.section_id = s.id
          )
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO home_section_items (id, section_id, item_kind, ref_id, sort_order)
        SELECT gen_random_uuid(), s.id, 'movie', c.content_id, c.sort_order
        FROM home_sections s
        JOIN coming_soon_items c ON true
        WHERE s.type = 'coming_soon'
          AND NOT EXISTS (
            SELECT 1 FROM home_section_items i WHERE i.section_id = s.id
          )
        ON CONFLICT DO NOTHING
        """
    )

    # One genre section per distinct genre_name from genre_rail_items (skip if already seeded).
    op.execute(
        """
        INSERT INTO home_sections (id, type, title, genre_name, is_visible, sort_order)
        SELECT gen_random_uuid(), 'genre', NULL, g.genre_name, true,
               100 + ROW_NUMBER() OVER (ORDER BY g.genre_name)
        FROM (SELECT DISTINCT genre_name FROM genre_rail_items) g
        WHERE NOT EXISTS (
            SELECT 1 FROM home_sections hs
            WHERE hs.type = 'genre'
              AND lower(hs.genre_name) = lower(g.genre_name)
        )
        """
    )

    op.execute(
        """
        INSERT INTO home_section_items (id, section_id, item_kind, ref_id, sort_order)
        SELECT gen_random_uuid(), hs.id, 'movie', g.content_id, g.sort_order
        FROM genre_rail_items g
        JOIN home_sections hs
          ON hs.type = 'genre' AND lower(hs.genre_name) = lower(g.genre_name)
        ON CONFLICT DO NOTHING
        """
    )

    # Link existing hero slides / banners when those sections have no items yet.
    op.execute(
        """
        INSERT INTO home_section_items (id, section_id, item_kind, ref_id, sort_order)
        SELECT gen_random_uuid(), s.id, 'hero_slide', h.id, h.sort_order
        FROM home_sections s
        JOIN hero_featured_items h ON true
        WHERE s.type = 'hero'
          AND NOT EXISTS (
            SELECT 1 FROM home_section_items i WHERE i.section_id = s.id
          )
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO home_section_items (id, section_id, item_kind, ref_id, sort_order)
        SELECT gen_random_uuid(), s.id, 'banner', b.id, b.sort_order
        FROM home_sections s
        JOIN promotion_banners b ON true
        WHERE s.type = 'banners'
          AND NOT EXISTS (
            SELECT 1 FROM home_section_items i WHERE i.section_id = s.id
          )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS home_section_items")
    op.execute("DROP TABLE IF EXISTS home_sections")
