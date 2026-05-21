"""Episode upload flow (multipart — API server never buffers video bytes):

  1. POST /series/{slug}/episodes/uploads/start
       → { content_id, upload_id, source_key, part_size, poster_key?, poster_upload_url? }

  2. GET  /series/{slug}/episodes/uploads/part-url?source_key=…&upload_id=…&part_number=N
       → { url }   (presigned PUT — client uploads the chunk directly to R2)

  3. POST /series/{slug}/episodes/uploads/complete
       → ContentRead   (completes multipart upload + creates episode record + queues transcode)

  4. POST /series/{slug}/episodes/uploads/abort
       → 204           (frees partial uploads on cancel / error)
"""

import asyncio
import re
import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, CurrentUser, DBSession
from app.models.content import Content
from app.models.series import Series
from app.models.transcode_job import TranscodeJob
from app.schemas.content import ContentRead, ContentUpdate, SeasonRead
from app.schemas.series import SeriesRead, SeriesUpdate
from app.services import storage
from app.services.content_delete import (
    delete_transcode_jobs_for_content,
    delete_transcode_jobs_for_series,
)

router = APIRouter(prefix="/series", tags=["series"])

_VALID_STATUSES = {"draft", "review", "scheduled", "published"}


# ── Helpers ───────────────────────────────────────────────────────────────────

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


async def _get_series_or_404(slug: str, db) -> Series:
    result = await db.execute(select(Series).where(Series.slug == slug))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")
    return series


# ── Series schemas ─────────────────────────────────────────────────────────────

class CreateSeriesBody(BaseModel):
    title: str
    monthly_price_usd: Decimal
    description: str | None = None
    genres: list[str] = []
    release_year: int | None = None
    rating: Decimal | None = None
    trailer_url: str | None = None


class SeriesPosterStart(BaseModel):
    poster_content_type: str = "image/jpeg"


class SeriesPosterStartRead(BaseModel):
    series_id: uuid.UUID
    poster_key: str
    poster_upload_url: str


# ── Episode upload schemas ─────────────────────────────────────────────────────

class EpisodeUploadStart(BaseModel):
    video_content_type: str = "video/mp4"
    poster_content_type: str | None = None


class EpisodeUploadStartRead(BaseModel):
    content_id: uuid.UUID
    upload_id: str
    source_key: str
    part_size: int
    poster_key: str | None = None
    poster_upload_url: str | None = None


class PartUrlRead(BaseModel):
    url: str


class MultipartPart(BaseModel):
    part_number: int
    etag: str


class EpisodeUploadComplete(BaseModel):
    content_id: uuid.UUID
    source_key: str
    upload_id: str
    parts: list[MultipartPart]
    title: str
    season_number: int
    episode_number: int
    description: str | None = None
    runtime: str | None = None
    status: str = "draft"
    trailer_url: str | None = None
    poster_key: str | None = None


class EpisodeUploadAbort(BaseModel):
    source_key: str
    upload_id: str


# ── Series CRUD ───────────────────────────────────────────────────────────────

@router.get("/", response_model=list[SeriesRead])
async def list_series(db: DBSession):
    result = await db.execute(select(Series).where(Series.is_published.is_(True)))
    return result.scalars().all()


@router.get("/{slug}", response_model=SeriesRead)
async def get_series(slug: str, db: DBSession, _: CurrentUser):
    return await _get_series_or_404(slug, db)


@router.post("/", response_model=SeriesRead, status_code=201)
async def create_series(data: CreateSeriesBody, db: DBSession, _: AdminUser):
    """Create a series record. Upload the poster separately via /series/{slug}/poster/start."""
    slug = await _unique_series_slug(data.title, db)
    series = Series(
        id=uuid.uuid4(),
        slug=slug,
        title=data.title,
        description=data.description,
        genres=data.genres,
        release_year=data.release_year,
        rating=data.rating,
        monthly_price_usd=data.monthly_price_usd,
        trailer_url=data.trailer_url,
    )
    db.add(series)
    await db.commit()
    await db.refresh(series)
    return series


@router.post("/{slug}/poster/start", response_model=SeriesPosterStartRead)
async def start_series_poster_upload(slug: str, data: SeriesPosterStart, db: DBSession, _: AdminUser):
    """Get a presigned URL to upload the series poster directly to R2."""
    series = await _get_series_or_404(slug, db)
    ext = {
        "image/jpeg": "jpg", "image/jpg": "jpg",
        "image/png": "png", "image/webp": "webp",
    }.get(data.poster_content_type, "jpg")
    poster_key = f"posters/series/{series.id}.{ext}"
    url = storage.generate_presigned_upload_url(poster_key, data.poster_content_type)
    return SeriesPosterStartRead(series_id=series.id, poster_key=poster_key, poster_upload_url=url)


@router.patch("/{slug}", response_model=SeriesRead)
async def update_series(slug: str, data: SeriesUpdate, db: DBSession, _: AdminUser):
    series = await _get_series_or_404(slug, db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(series, field, value)
    await db.commit()
    await db.refresh(series)
    return series


@router.delete("/{slug}", status_code=204)
async def delete_series(slug: str, db: DBSession, _: AdminUser):
    series = await _get_series_or_404(slug, db)
    await delete_transcode_jobs_for_series(db, series.id)
    await db.delete(series)
    await db.commit()


# ── Episode read endpoints ─────────────────────────────────────────────────────

@router.get("/{slug}/episodes", response_model=list[SeasonRead])
async def list_episodes(slug: str, db: DBSession, _: CurrentUser):
    """All published episodes for a series, grouped and sorted by season."""
    series = await _get_series_or_404(slug, db)

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


# ── Episode upload endpoints ───────────────────────────────────────────────────

@router.post("/{slug}/episodes/uploads/start", response_model=EpisodeUploadStartRead)
async def start_episode_upload(slug: str, data: EpisodeUploadStart, db: DBSession, _: AdminUser):
    """Initiate a multipart upload for an episode. Returns upload_id + part_size.

    The client must split the video file into chunks of `part_size` bytes and
    PUT each chunk to R2 using the URL from /episodes/uploads/part-url. The API
    server never receives any video bytes.
    """
    series = await _get_series_or_404(slug, db)

    content_id = uuid.uuid4()
    source_key = f"raw/{content_id}.mp4"

    loop = asyncio.get_event_loop()
    upload_id = await loop.run_in_executor(
        None, storage.create_multipart_upload, source_key, data.video_content_type
    )

    poster_key: str | None = None
    poster_upload_url: str | None = None
    if data.poster_content_type:
        ext = {
            "image/jpeg": "jpg", "image/jpg": "jpg",
            "image/png": "png", "image/webp": "webp",
        }.get(data.poster_content_type, "jpg")
        poster_key = f"posters/{content_id}.{ext}"
        poster_upload_url = storage.generate_presigned_upload_url(
            poster_key, data.poster_content_type
        )

    return EpisodeUploadStartRead(
        content_id=content_id,
        upload_id=upload_id,
        source_key=source_key,
        part_size=storage.MULTIPART_PART_SIZE,
        poster_key=poster_key,
        poster_upload_url=poster_upload_url,
    )


@router.get("/{slug}/episodes/uploads/part-url", response_model=PartUrlRead)
async def get_episode_part_url(
    slug: str,
    _: AdminUser,
    source_key: str = Query(..., description="source_key from /episodes/uploads/start"),
    upload_id: str = Query(..., description="upload_id from /episodes/uploads/start"),
    part_number: int = Query(..., ge=1, le=10000, description="1-based chunk index"),
):
    """Return a presigned PUT URL for one episode video chunk.

    The client calls this once per part, then PUTs the raw bytes directly to
    R2. Save the ETag from each response header — required for /uploads/complete.
    """
    url = storage.generate_presigned_part_url(source_key, upload_id, part_number)
    return PartUrlRead(url=url)


@router.post("/{slug}/episodes/uploads/complete", response_model=ContentRead, status_code=201)
async def complete_episode_upload(slug: str, data: EpisodeUploadComplete, db: DBSession, _: AdminUser):
    """Assemble the uploaded parts, then create the episode record and transcode job."""
    if data.status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUSES)}")

    expected_source_key = f"raw/{data.content_id}.mp4"
    if data.source_key != expected_source_key:
        raise HTTPException(status_code=422, detail="source_key does not match content_id")

    if not data.parts:
        raise HTTPException(status_code=422, detail="parts list is empty")

    series = await _get_series_or_404(slug, db)

    loop = asyncio.get_event_loop()

    r2_parts = sorted(
        [{"PartNumber": p.part_number, "ETag": p.etag} for p in data.parts],
        key=lambda x: x["PartNumber"],
    )
    try:
        await loop.run_in_executor(
            None, storage.complete_multipart_upload, data.source_key, data.upload_id, r2_parts
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Failed to complete multipart upload: {exc}")

    if data.poster_key:
        poster_exists = await loop.run_in_executor(None, storage.object_exists, data.poster_key)
        if not poster_exists:
            raise HTTPException(status_code=409, detail="Poster upload is not available in storage yet")

    ep_slug = await _unique_content_slug(
        f"{slug}-s{data.season_number:02d}e{data.episode_number:02d}", db
    )

    episode = Content(
        id=data.content_id,
        type="episode",
        series_id=series.id,
        season_number=data.season_number,
        episode_number=data.episode_number,
        slug=ep_slug,
        title=data.title,
        description=data.description,
        runtime=data.runtime,
        poster_key=data.poster_key,
        trailer_url=data.trailer_url,
        status=data.status,
        is_published=(data.status == "published"),
        transcode_status="pending",
    )
    db.add(episode)
    db.add(TranscodeJob(content_id=data.content_id, source_key=data.source_key))

    await db.commit()
    await db.refresh(episode)
    return episode


@router.post("/{slug}/episodes/uploads/abort", status_code=204)
async def abort_episode_upload(slug: str, data: EpisodeUploadAbort, _: AdminUser):
    """Cancel an in-progress episode multipart upload and free the stored parts on R2."""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, storage.abort_multipart_upload, data.source_key, data.upload_id
        )
    except Exception:
        pass  # already completed or never existed


# ── Episode CRUD ──────────────────────────────────────────────────────────────

@router.patch("/{slug}/episodes/{episode_slug}", response_model=ContentRead)
async def update_episode(
    slug: str, episode_slug: str, data: ContentUpdate, db: DBSession, _: AdminUser
):
    series = await _get_series_or_404(slug, db)

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
    series = await _get_series_or_404(slug, db)

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

    await delete_transcode_jobs_for_content(db, episode.id)
    await db.delete(episode)
    await db.commit()
