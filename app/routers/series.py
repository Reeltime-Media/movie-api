import asyncio
import io
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, CurrentUser, DBSession
from app.models.content import Content
from app.models.series import Series
from app.models.transcode_job import TranscodeJob
from app.schemas.content import ContentRead, ContentUpdate, SeasonRead
from app.schemas.series import SeriesRead, SeriesUpdate
from app.services import storage

router = APIRouter(prefix="/series", tags=["series"])

_VALID_STATUSES = {"draft", "review", "scheduled", "published"}


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


async def _unique_content_slug(base: str, db) -> str:
    slug = _slugify(base)
    existing = await db.execute(select(Content).where(Content.slug == slug))
    if not existing.scalar_one_or_none():
        return slug
    return f"{slug}-{uuid.uuid4().hex[:6]}"


async def _unique_series_slug(base: str, db) -> str:
    slug = _slugify(base)
    existing = await db.execute(select(Series).where(Series.slug == slug))
    if not existing.scalar_one_or_none():
        return slug
    return f"{slug}-{uuid.uuid4().hex[:6]}"


# ── Series CRUD ───────────────────────────────────────────────────────────────

@router.get("/", response_model=list[SeriesRead])
async def list_series(db: DBSession, _: CurrentUser):
    result = await db.execute(select(Series).where(Series.is_published.is_(True)))
    return result.scalars().all()


@router.get("/{slug}", response_model=SeriesRead)
async def get_series(slug: str, db: DBSession, _: CurrentUser):
    result = await db.execute(select(Series).where(Series.slug == slug))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")
    return series


@router.post("/", response_model=SeriesRead, status_code=201)
async def create_series(
    db: DBSession,
    _: AdminUser,
    title: Annotated[str, Form()],
    monthly_price_usd: Annotated[str, Form()],
    description: Annotated[str | None, Form()] = None,
    genres: Annotated[str | None, Form(description='JSON array e.g. ["Action","Drama"]')] = None,
    release_year: Annotated[int | None, Form()] = None,
    rating: Annotated[str | None, Form(description="Decimal e.g. 8.7")] = None,
    poster: Annotated[UploadFile | None, File(description="Series poster image")] = None,
):
    try:
        price = Decimal(monthly_price_usd)
    except InvalidOperation:
        raise HTTPException(status_code=422, detail="Invalid monthly_price_usd value")

    parsed_rating: Decimal | None = None
    if rating is not None:
        try:
            parsed_rating = Decimal(rating)
        except InvalidOperation:
            raise HTTPException(status_code=422, detail="Invalid rating value")

    parsed_genres: list[str] = []
    if genres:
        try:
            parsed_genres = json.loads(genres)
            if not isinstance(parsed_genres, list):
                raise ValueError
        except (ValueError, Exception):
            raise HTTPException(status_code=422, detail='genres must be a JSON array e.g. ["Action","Drama"]')

    slug = await _unique_series_slug(title, db)
    series_id = uuid.uuid4()

    poster_key: str | None = None
    if poster and poster.filename:
        ext = poster.filename.rsplit(".", 1)[-1].lower() if "." in poster.filename else "jpg"
        poster_key = f"posters/series/{series_id}.{ext}"
        poster_bytes = await poster.read()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, storage.upload_fileobj, io.BytesIO(poster_bytes), poster_key,
            poster.content_type or "image/jpeg",
        )

    series = Series(
        id=series_id,
        slug=slug,
        title=title,
        description=description,
        genres=parsed_genres,
        release_year=release_year,
        rating=parsed_rating,
        monthly_price_usd=price,
        poster_key=poster_key,
    )
    db.add(series)
    await db.commit()
    await db.refresh(series)
    return series


@router.patch("/{slug}", response_model=SeriesRead)
async def update_series(slug: str, data: SeriesUpdate, db: DBSession, _: AdminUser):
    result = await db.execute(select(Series).where(Series.slug == slug))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(series, field, value)
    await db.commit()
    await db.refresh(series)
    return series


@router.delete("/{slug}", status_code=204)
async def delete_series(slug: str, db: DBSession, _: AdminUser):
    result = await db.execute(select(Series).where(Series.slug == slug))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")
    await db.delete(series)
    await db.commit()


# ── Episode CRUD ──────────────────────────────────────────────────────────────

@router.get("/{slug}/episodes", response_model=list[SeasonRead])
async def list_episodes(slug: str, db: DBSession, _: CurrentUser):
    """All published episodes for a series, grouped and sorted by season."""
    result = await db.execute(select(Series).where(Series.slug == slug))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")

    eps_result = await db.execute(
        select(Content)
        .where(Content.series_id == series.id, Content.is_published.is_(True))
        .order_by(Content.season_number, Content.episode_number)
    )
    episodes = eps_result.scalars().all()

    seasons: dict[int, list[Content]] = {}
    for ep in episodes:
        sn = ep.season_number or 1
        seasons.setdefault(sn, []).append(ep)

    return [
        SeasonRead(season_number=sn, episodes=eps)
        for sn, eps in sorted(seasons.items())
    ]


@router.post("/{slug}/episodes", response_model=ContentRead, status_code=201)
async def add_episode(
    slug: str,
    db: DBSession,
    _: AdminUser,
    title: Annotated[str, Form()],
    season_number: Annotated[int, Form()],
    episode_number: Annotated[int, Form()],
    video: Annotated[UploadFile, File(description="Episode video file (mp4 recommended)")],
    description: Annotated[str | None, Form()] = None,
    runtime: Annotated[str | None, Form(description='e.g. "45m"')] = None,
    status: Annotated[str, Form()] = "draft",
    trailer_url: Annotated[str | None, Form(description="YouTube URL for the trailer")] = None,
    poster: Annotated[UploadFile | None, File(description="Episode poster image")] = None,
):
    if status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUSES)}")

    result = await db.execute(select(Series).where(Series.slug == slug))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")

    content_id = uuid.uuid4()
    source_key = f"raw/{content_id}.mp4"
    loop = asyncio.get_event_loop()

    video_bytes = await video.read()
    await loop.run_in_executor(
        None, storage.upload_fileobj, io.BytesIO(video_bytes), source_key, "video/mp4"
    )

    poster_key: str | None = None
    if poster and poster.filename:
        ext = poster.filename.rsplit(".", 1)[-1].lower() if "." in poster.filename else "jpg"
        poster_key = f"posters/{content_id}.{ext}"
        poster_bytes = await poster.read()
        await loop.run_in_executor(
            None, storage.upload_fileobj, io.BytesIO(poster_bytes), poster_key,
            poster.content_type or "image/jpeg",
        )

    ep_slug = await _unique_content_slug(f"{slug}-s{season_number:02d}e{episode_number:02d}", db)

    episode = Content(
        id=content_id,
        type="episode",
        series_id=series.id,
        season_number=season_number,
        episode_number=episode_number,
        slug=ep_slug,
        title=title,
        description=description,
        runtime=runtime,
        poster_key=poster_key,
        trailer_url=trailer_url,
        status=status,
        is_published=(status == "published"),
        transcode_status="pending",
    )
    db.add(episode)
    db.add(TranscodeJob(content_id=content_id, source_key=source_key))

    await db.commit()
    await db.refresh(episode)
    return episode


@router.patch("/{slug}/episodes/{episode_slug}", response_model=ContentRead)
async def update_episode(
    slug: str, episode_slug: str, data: ContentUpdate, db: DBSession, _: AdminUser
):
    series_result = await db.execute(select(Series).where(Series.slug == slug))
    series = series_result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")

    ep_result = await db.execute(
        select(Content).where(
            Content.slug == episode_slug,
            Content.series_id == series.id,
            Content.type == "episode",
        )
    )
    episode = ep_result.scalar_one_or_none()
    if not episode:
        raise NotFoundError("Episode not found")

    updates = data.model_dump(exclude_unset=True)
    if "status" in updates:
        if updates["status"] not in _VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUSES)}")
        updates.setdefault("is_published", updates["status"] == "published")

    for field, value in updates.items():
        setattr(episode, field, value)

    await db.commit()
    await db.refresh(episode)
    return episode


@router.delete("/{slug}/episodes/{episode_slug}", status_code=204)
async def delete_episode(slug: str, episode_slug: str, db: DBSession, _: AdminUser):
    series_result = await db.execute(select(Series).where(Series.slug == slug))
    series = series_result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")

    ep_result = await db.execute(
        select(Content).where(
            Content.slug == episode_slug,
            Content.series_id == series.id,
            Content.type == "episode",
        )
    )
    episode = ep_result.scalar_one_or_none()
    if not episode:
        raise NotFoundError("Episode not found")

    await db.delete(episode)
    await db.commit()
