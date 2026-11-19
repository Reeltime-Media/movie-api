"""Seed demo content for the TV5 Entertainment app from the Reeltime catalog.

- Copies a few published Reeltime series, with their published episodes, into TV5.
  The copies are new rows (slug ``tv5-<original>``) that point at the same R2 poster,
  banner and HLS files; Reeltime keeps its originals unchanged. Deleting a title never
  deletes R2 files, so sharing the keys is safe.
- Creates published Kun Khmer matches whose video and poster are borrowed from one
  Reeltime movie, as placeholders until the real fights are uploaded in the admin.
- Creates a TV5 monthly plan if TV5 has no plan yet.

Idempotent: rows whose slug or plan code already exists are skipped.

    cd movie-api
    PYTHONPATH=. python seed/seed_tv5_demo.py --dry-run   # show what would be copied
    PYTHONPATH=. python seed/seed_tv5_demo.py
"""

from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from decimal import Decimal

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.apps import REELTIME, TV5
from app.db_connect import sqlalchemy_engine_kwargs
from app.models.content import Content
from app.models.match_details import MatchDetails
from app.models.series import Series
from app.models.subscription_plan import SubscriptionPlan

PREFIX = "tv5-"

# The fight cards the TV5 app showed as samples before it had a backend.
MATCHES = (
    ("Moeun Sokhuch", "Ahmad Masouminia", "DAZZ Kun Khmer Battle"),
    ("Mon Moeuy", "Hossein Ekkasit", "Cambodia Sport+"),
    ("South Bunthy", "Mohammad Ashraf Alizada", "TV5 Cambodia Sport"),
)

TV5_PLAN = {
    "code": "tv5_monthly",
    "name": "TV5 Monthly",
    "description": "30 days of TV5 series and Kun Khmer fights.",
    "price_usd": Decimal("2.99"),
    "billing_interval_days": 30,
}

# Never copied: identity, ownership and generated columns.
_SKIP = {"id", "slug", "app", "series_id", "search_vector", "created_at", "updated_at"}


def _copy(row, model, **overrides):
    values = {
        col.key: getattr(row, col.key)
        for col in model.__table__.columns
        if col.key not in _SKIP and not col.computed
    }
    values.update(overrides)
    return model(**values)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _playable():
    return (
        Content.is_published.is_(True),
        Content.transcode_status == "ready",
        Content.hls_master_key.is_not(None),
    )


async def _slug_taken(db: AsyncSession, model, slug: str) -> bool:
    return bool(await db.scalar(select(exists().where(model.slug == slug))))


async def _pick_series(db: AsyncSession, count: int, slugs: list[str] | None) -> list[Series]:
    playable_episode = exists().where(Content.series_id == Series.id, *_playable())
    stmt = select(Series).where(
        Series.app == REELTIME,
        Series.is_published.is_(True),
        Series.is_short_movie.is_(False),
        playable_episode,
    )
    if slugs:
        stmt = stmt.where(Series.slug.in_(slugs))
    else:
        stmt = stmt.order_by(Series.sort_order.asc(), Series.created_at.desc()).limit(count)
    return list((await db.execute(stmt)).scalars().all())


async def _pick_placeholder_movie(db: AsyncSession, slug: str | None) -> Content | None:
    stmt = select(Content).where(
        Content.app == REELTIME,
        Content.type == "single",
        Content.poster_key.is_not(None),
        *_playable(),
    )
    if slug:
        stmt = stmt.where(Content.slug == slug)
    else:
        stmt = stmt.order_by(Content.sort_order.asc(), Content.created_at.desc())
    return (await db.execute(stmt.limit(1))).scalar_one_or_none()


async def _copy_series(db: AsyncSession, source: Series, dry_run: bool) -> str:
    episodes = list(
        (
            await db.execute(
                select(Content)
                .where(Content.series_id == source.id, Content.type == "episode", *_playable())
                .order_by(Content.season_number, Content.episode_number)
            )
        )
        .scalars()
        .all()
    )
    slug = PREFIX + source.slug
    if await _slug_taken(db, Series, slug):
        return f"skip series {slug} (exists)"
    if dry_run:
        return f"would copy series {source.title!r} -> {slug} with {len(episodes)} episodes"

    series = _copy(source, Series, id=uuid.uuid4(), slug=slug, app=TV5)
    db.add(series)
    await db.flush()
    copied = 0
    for ep in episodes:
        ep_slug = PREFIX + ep.slug
        if await _slug_taken(db, Content, ep_slug):
            continue
        # TV5 never sells titles one by one, so the copy carries no price.
        db.add(_copy(ep, Content, slug=ep_slug, app=TV5, series_id=series.id, price_usd=None))
        copied += 1
    return f"copied series {source.title!r} -> {slug} with {copied} episodes"


async def _create_matches(db: AsyncSession, movie: Content, dry_run: bool) -> list[str]:
    lines = []
    for index, (red, blue, event) in enumerate(MATCHES):
        title = f"{red} vs {blue}"
        slug = f"{PREFIX}kun-khmer-{_slugify(title)}"
        if await _slug_taken(db, Content, slug):
            lines.append(f"skip match {slug} (exists)")
            continue
        # The first fight is free so the app has something anyone can play.
        free = index == 0
        if dry_run:
            lines.append(f"would create match {title!r} ({event}) free={free}")
            continue
        content = Content(
            id=uuid.uuid4(),
            type="single",
            app=TV5,
            slug=slug,
            title=title,
            description=f"Kun Khmer: {title} at {event}.",
            genres=["Kun Khmer"],
            region="Cambodia",
            runtime=movie.runtime,
            duration_seconds=movie.duration_seconds,
            poster_key=movie.poster_key,
            banner_key=movie.banner_key,
            hls_master_key=movie.hls_master_key,
            # Every single title needs a price (DB check); TV5 never sells one, so 0
            # like the admin's match form.
            price_usd=Decimal("0"),
            transcode_status="ready",
            status="published",
            is_published=True,
            is_free=free,
            sort_order=index,
        )
        db.add(content)
        await db.flush()
        db.add(
            MatchDetails(
                content_id=content.id, red_fighter=red, blue_fighter=blue, event_name=event
            )
        )
        lines.append(f"created match {title!r} ({event}) free={free}")
    return lines


async def _ensure_plan(db: AsyncSession, dry_run: bool) -> str:
    count = await db.scalar(
        select(func.count()).select_from(SubscriptionPlan).where(SubscriptionPlan.app == TV5)
    )
    if count:
        return f"skip plan ({count} TV5 plan(s) exist)"
    if await db.scalar(select(exists().where(SubscriptionPlan.code == TV5_PLAN["code"]))):
        return f"skip plan ({TV5_PLAN['code']} code is taken)"
    if dry_run:
        return f"would create plan {TV5_PLAN['code']} ${TV5_PLAN['price_usd']}"
    db.add(SubscriptionPlan(id=uuid.uuid4(), app=TV5, is_active=True, sort_order=0, **TV5_PLAN))
    return f"created plan {TV5_PLAN['code']} ${TV5_PLAN['price_usd']}"


async def seed(args: argparse.Namespace) -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.effective_database_url,
        **sqlalchemy_engine_kwargs(
            settings.effective_database_url,
            debug=False,
            # Skip project CA — local macOS often fails chain verify on Supabase.
            ssl_root_cert=None,
            allow_insecure_ssl=True,
        ),
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            sources = await _pick_series(db, args.series, args.series_slug)
            movie = await _pick_placeholder_movie(db, args.placeholder_movie)
            if not sources:
                raise SystemExit("No published Reeltime series with a playable episode.")
            if not movie:
                raise SystemExit("No published, transcoded Reeltime movie for the placeholder.")
            print(f"placeholder video: {movie.title!r} ({movie.slug})")
            for source in sources:
                print(await _copy_series(db, source, args.dry_run))
            for line in await _create_matches(db, movie, args.dry_run):
                print(line)
            print(await _ensure_plan(db, args.dry_run))
            if args.dry_run:
                await db.rollback()
                print("dry run: nothing written")
            else:
                await db.commit()
                print("committed")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--series", type=int, default=4, help="how many series to copy")
    parser.add_argument(
        "--series-slug", action="append", help="copy this Reeltime series (repeatable)"
    )
    parser.add_argument("--placeholder-movie", help="Reeltime movie slug for match videos")
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(seed(parser.parse_args()))


if __name__ == "__main__":
    main()
