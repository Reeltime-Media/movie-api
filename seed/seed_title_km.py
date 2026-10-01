"""
Backfill Khmer titles (title_km) for catalog rows that are missing them.

Idempotent: only fills NULL / blank title_km. Never overwrites existing values.

    cd movie-api
    PYTHONPATH=. python seed/seed_title_km.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db_connect import sqlalchemy_engine_kwargs

# Movies / singles (content.type = 'single')
MOVIE_TITLE_KM: dict[str, str] = {
    "after-school-2-2017": "ក្រោយម៉ោងរៀន ២",
    "clayface-2026": "បុរសដីឥដ្ឋ",
    "crimson-horizon": "ផ្តេកទិដ្ឋក្រហម",
    "get-lost-2018": "បាត់បង់",
    "ghosts-of-tonle-sap": "ខ្មោចទន្លេសាប",
    "insidious-out-of-the-further-2026": "សំឡេងអវិញ្ញាណ៖ ចេញពីពិភពខ្មោច",
    "kelam-2019": "ខេឡាំ",
    "lee-cronins-the-mummy-2026": "ម៉ាំមី",
    "midnight-requiem": "បទរំលឹកពាក់កណ្តាលអធ្រាត្រ",
    "mutiny-2026": "ការបះបោរ",
    "practical-magic-2-2026": "វេទមន្តជាក់ស្តែង ២",
    "street-fighter-2026": "អ្នកប្រយុទ្ធតាមផ្លូវ",
    "the-dog-stars-2026": "ផ្កាយឆ្កែ",
}

# Series
SERIES_TITLE_KM: dict[str, str] = {
    "carol-of-zhenguan": "បទចម្រៀងឆេនគ្វាន",
    "dragon-gate-posthouse-2018": "សណ្ឋាគារមាត់ទ្វារនាគ",
    "dragon-love-1999": "ស្នេហានាគ",
    "dual-travel-ultimate-fortune-or-double-dimension-tycoon-2025": "ធ្វើដំណើរពីរវិមាត្រ",
    "endless-love-2025": "ស្នេហាគ្មានទីបញ្ចប់",
    "2-good-luck-2024": "សំណាងល្អ",
    "great-general-han-xin-2009": "មហាសេនាបតីហានស៊ីន",
    "1-half-awake-2026": "ភ្ញាក់ពាក់កណ្តាល",
    "happy-love-forever-2010": "ស្នេហារីករាយអស់កល្ប",
    "i-can-hear-the-voices-of-animals-2024": "ខ្ញុំស្តាប់សំឡេងសត្វបាន",
    "i-crafted-the-ancient-xuanyuan-sword-2025": "ខ្ញុំបង្កើតដាវបុរាណស៊ួនយាន",
    "inspiring-generation-2014": "ជំនាន់បំផុសគំនិត",
    "iron-masked-singer-2010": "អ្នកចម្រៀងម៉ាស់ដែក",
    "let-love-evolve-into-pearl-rain": "អោយស្នេហាក្លាយជាភ្លៀងគុជ",
    "live-streaming-in-the-spirit-realm-2024": "ផ្សាយផ្ទាល់ក្នុងពិភពវិញ្ញាណ",
    "love-line-2025": "ខ្សែស្នេហ៍",
    "my-connections-span-three-realms-2025": "ទំនាក់ទំនងរបស់ខ្ញុំគ្រប់បីពិភព",
    "return-of-love-2025": "ការត្រឡប់មកវិញនៃស្នេហ៍",
    "royal-tramp-2008": "ព្រះអង្គម្ចាស់កំប្លែង",
    "shaolin-king-of-martial-arts-2002": "ស្តេចសិល្បៈប្រយុទ្ធសៅលីង",
    "strange-hero-ouyang-de-2012": "វីរបុរសចម្លែកអូវ៉ាងតេ",
    "su-dong-po-2012": "ស៊ូតុងផូ",
    "tears-of-a-bride-2011": "ទឹកភ្នែកកូនក្រមុំ",
    "the-gifted-quadruplets-2024": "កូនភ្លោះបួននាក់មានទេពកោសល្យ",
    "the-great-revival-2007": "ការរស់ឡើងវិញដ៏អស្ចារ្យ",
    "the-last-love-2025": "ស្នេហាចុងក្រោយ",
    "the-luckiest-man-2003": "បុរសសំណាងបំផុត",
    "orphan-of-the-zhao-family": "ក្មេងកំព្រាត្រកូលឆៅ",
    "the-road-of-love-in-reverse-2025": "ផ្លូវស្នេហ៍បញ្ច្រាស",
    "wow-the-ancient-imperial-concubine-traveled-through-time-and-space-to-my-home-or-help-my-harem-traveled-to-modern-times-2024": "នាងស្នំបុរាណធ្វើដំណើរពេលវេលាមកផ្ទះខ្ញុំ",
}


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        **sqlalchemy_engine_kwargs(settings.database_url),
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        movie_updated = 0
        for slug, title_km in MOVIE_TITLE_KM.items():
            result = await db.execute(
                text(
                    """
                    UPDATE content
                    SET title_km = :title_km, updated_at = NOW()
                    WHERE slug = :slug
                      AND type = 'single'
                      AND (title_km IS NULL OR btrim(title_km) = '')
                    """
                ),
                {"slug": slug, "title_km": title_km},
            )
            if result.rowcount:
                movie_updated += result.rowcount
                print(f"movie  {slug} → {title_km}")

        series_updated = 0
        for slug, title_km in SERIES_TITLE_KM.items():
            result = await db.execute(
                text(
                    """
                    UPDATE series
                    SET title_km = :title_km, updated_at = NOW()
                    WHERE slug = :slug
                      AND (title_km IS NULL OR btrim(title_km) = '')
                    """
                ),
                {"slug": slug, "title_km": title_km},
            )
            if result.rowcount:
                series_updated += result.rowcount
                print(f"series {slug} → {title_km}")

        await db.commit()

        remaining_movies = await db.scalar(
            text(
                """
                SELECT count(*)::int FROM content
                WHERE type = 'single'
                  AND (title_km IS NULL OR btrim(title_km) = '')
                """
            )
        )
        remaining_series = await db.scalar(
            text(
                """
                SELECT count(*)::int FROM series
                WHERE title_km IS NULL OR btrim(title_km) = ''
                """
            )
        )

    await engine.dispose()
    print(
        f"\nDone. Updated movies={movie_updated} series={series_updated}. "
        f"Still missing movies={remaining_movies} series={remaining_series}."
    )


if __name__ == "__main__":
    asyncio.run(main())
