"""Episode upload flow (multipart — API server never buffers video bytes):

  1. POST /series/{slug}/episodes/uploads/start  (requires file_size_bytes)
       → { content_id, upload_id, source_key, part_size, part_urls[], poster_key?, poster_upload_url? }

  2. GET  /series/{slug}/episodes/uploads/part-url?source_key=…&upload_id=…&part_number=N
       → { url }   (optional fallback — start returns all part URLs in one response)

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
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.core.money import validate_usd_price
from app.dependencies import AdminUser, CurrentUser, DBSession
from app.models.content import Content
from app.models.series import Series
from app.models.transcode_job import TranscodeJob
from app.schemas.content import ContentRead, ContentUpdate, SeasonRead
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.schemas.series import SeriesListItemRead, SeriesRead, SeriesUpdate
from app.services import storage
from app.services import r2_keys
from app.services.pagination import paginate_query
from app.services.content_delete import (
    delete_content_dependencies,
    delete_content_dependencies_for_series,
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


async def _get_series_or_404(slug: str, db, *, published_only: bool = False) -> Series:
    stmt = select(Series).where(Series.slug == slug)
    if published_only:
        stmt = stmt.where(Series.is_published.is_(True))
    result = await db.execute(stmt)
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

    @field_validator("monthly_price_usd")
    @classmethod
    def check_monthly_price_usd(cls, value: Decimal) -> Decimal:
        return validate_usd_price(value)


class SeriesPosterStart(BaseModel):
    poster_content_type: str = "image/jpeg"


class SeriesPosterStartRead(BaseModel):
    series_id: uuid.UUID
    poster_key: str
    poster_upload_url: str


# ── Episode upload schemas ─────────────────────────────────────────────────────

class EpisodeUploadStart(BaseModel):
    season_number: int
    episode_number: int
    file_size_bytes: int = Field(gt=0, description="Raw video file size — used to presign all part URLs")
    video_content_type: str = "video/mp4"
    poster_content_type: str | None = None


class MultipartPartUrl(BaseModel):
    part_number: int
    url: str


class EpisodeUploadStartRead(BaseModel):
    content_id: uuid.UUID
    episode_slug: str
    upload_id: str
    source_key: str
    part_size: int
    part_count: int
    part_urls: list[MultipartPartUrl]
    poster_key: str | None = None
    poster_upload_url: str | None = None


class PartUrlRead(BaseModel):
    url: str


class MultipartPart(BaseModel):
    part_number: int
    etag: str


class EpisodeUploadComplete(BaseModel):
    content_id: uuid.UUID
    episode_slug: str
    source_key: str
    upload_id: str
    parts: list[MultipartPart]
    title: str
    season_number: int
    episode_number: int
    description: str | None = None
    runtime: str | None = None
    status: str = "draft"
    is_free: bool = False
    trailer_url: str | None = None
    poster_key: str | None = None


class EpisodeUploadAbort(BaseModel):
    source_key: str
    upload_id: str


# ── Series CRUD ───────────────────────────────────────────────────────────────

@router.get("/", response_model=PaginatedResponse[SeriesListItemRead])
async def list_series(db: DBSession, pagination: PaginationDep):
    stmt = (
        select(Series)
        .where(Series.is_published.is_(True))
        .order_by(Series.created_at.desc())
    )
    items, total = await paginate_query(
        db,
        stmt,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return build_paginated_response(
        [SeriesListItemRead.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{slug}", response_model=SeriesRead)
async def get_series(slug: str, db: DBSession, current_user: CurrentUser):
    published_only = current_user.role != "admin"
    return await _get_series_or_404(slug, db, published_only=published_only)


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
    poster_key = r2_keys.series_poster_key(series.slug, data.poster_content_type)
    url = storage.generate_presigned_upload_url(poster_key, data.poster_content_type)
    return SeriesPosterStartRead(series_id=series.id, poster_key=poster_key, poster_upload_url=url)


@router.patch("/{slug}", response_model=SeriesRead)
async def update_series(slug: str, data: SeriesUpdate, db: DBSession, _: AdminUser):
    series = await _get_series_or_404(slug, db)
    updates = data.model_dump(exclude_unset=True)
    # monthly_price_usd is NOT NULL — ignore explicit null from clients
    if updates.get("monthly_price_usd") is None:
        updates.pop("monthly_price_usd", None)
    for field, value in updates.items():
        setattr(series, field, value)
    await db.commit()
    await db.refresh(series)
    return series


@router.delete("/{slug}", status_code=204)
async def delete_series(slug: str, db: DBSession, _: AdminUser):
    series = await _get_series_or_404(slug, db)
    await delete_content_dependencies_for_series(db, series.id)
    await db.delete(series)
    await db.commit()


# ── Episode read endpoints ─────────────────────────────────────────────────────

@router.get("/{slug}/episodes", response_model=list[SeasonRead])
async def list_episodes(slug: str, db: DBSession):
    """Published episodes for a series (public — used for free-episode discovery on the catalog)."""
    series = await _get_series_or_404(slug, db, published_only=True)

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
    episode_slug = await _unique_content_slug(
        f"{slug}-s{data.season_number:02d}e{data.episode_number:02d}",
        db,
    )
    source_key = r2_keys.episode_source_key(slug, episode_slug)

    loop = asyncio.get_event_loop()
    upload_id = await loop.run_in_executor(
        None, storage.create_multipart_upload, source_key, data.video_content_type
    )

    poster_key: str | None = None
    poster_upload_url: str | None = None
    if data.poster_content_type:
        poster_key = r2_keys.episode_poster_key(slug, episode_slug, data.poster_content_type)
        poster_upload_url = storage.generate_presigned_upload_url(
            poster_key, data.poster_content_type
        )

    part_count = storage.multipart_part_count(data.file_size_bytes)
    part_urls = storage.generate_presigned_part_urls(source_key, upload_id, part_count)

    return EpisodeUploadStartRead(
        content_id=content_id,
        episode_slug=episode_slug,
        upload_id=upload_id,
        source_key=source_key,
        part_size=storage.MULTIPART_PART_SIZE,
        part_count=part_count,
        part_urls=[MultipartPartUrl(**entry) for entry in part_urls],
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

    series = await _get_series_or_404(slug, db)

    expected_source_key = r2_keys.episode_source_key(slug, data.episode_slug)
    if data.source_key != expected_source_key:
        raise HTTPException(status_code=422, detail="source_key does not match episode_slug")

    if data.poster_key and not r2_keys.is_episode_asset_key(slug, data.episode_slug, data.poster_key):
        raise HTTPException(status_code=422, detail="poster_key does not match episode_slug")

    if not data.parts:
        raise HTTPException(status_code=422, detail="parts list is empty")

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

    episode = Content(
        id=data.content_id,
        type="episode",
        series_id=series.id,
        season_number=data.season_number,
        episode_number=data.episode_number,
        slug=data.episode_slug,
        title=data.title,
        description=data.description,
        runtime=data.runtime,
        poster_key=data.poster_key,
        trailer_url=data.trailer_url,
        status=data.status,
        is_published=(data.status == "published"),
        is_free=data.is_free,
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

    await delete_content_dependencies(db, episode.id)
    await db.delete(episode)
    await db.commit()
