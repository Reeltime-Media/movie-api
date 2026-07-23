"""Episode upload flow (multipart — API server never buffers video bytes):

  1. POST /series/{slug}/episodes/uploads/start  (requires file_size_bytes)
       → { content_id, upload_id, source_key, part_size, part_urls[], poster_key?, poster_upload_url? }

  2. GET  /series/{slug}/episodes/uploads/part-url?source_key=…&upload_id=…&part_number=N
       → { url }   (optional fallback — start returns all part URLs in one response)

  3. POST /series/{slug}/episodes/uploads/complete
       → ContentRead   (completes multipart upload + creates episode record + queues transcode)

  4. POST /series/{slug}/episodes/uploads/abort
       → 204           (frees partial uploads on cancel / error)

Episode asset replace (existing episode — admin edit):

  5. POST /series/{slug}/episodes/{episode_slug}/assets/start
  6. POST /series/{slug}/episodes/{episode_slug}/assets/complete
"""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.core.content_status import validate_content_status
from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, DBSession, OptionalUser
from app.models.content import Content
from app.models.series import Series
from app.models.transcode_job import TranscodeJob
from app.schemas.content import ContentRead, ContentUpdate, SeasonRead
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.schemas.series import (
    CreateSeriesBody,
    EpisodeAssetUploadComplete,
    EpisodeAssetUploadStart,
    EpisodeAssetUploadStartRead,
    EpisodeUploadAbort,
    EpisodeUploadComplete,
    EpisodeUploadStart,
    EpisodeUploadStartRead,
    SeriesBannerStart,
    SeriesBannerStartRead,
    SeriesListItemRead,
    SeriesPosterStart,
    SeriesPosterStartRead,
    SeriesRead,
    SeriesUpdate,
)
from app.schemas.upload import PartUrlRead
from app.services import r2_keys, storage
from app.services.content_access import user_has_active_subscription
from app.services.content_delete import (
    delete_content_dependencies,
    delete_series_and_dependencies,
)
from app.services.content_slug import unique_content_slug, unique_series_slug
from app.services.content_upload import (
    abort_multipart_upload,
    complete_multipart_upload,
    presigned_part_url,
    start_multipart_upload,
    verify_storage_objects_exist,
)
from app.services.image_process import optimize_r2_image
from app.services.pagination import paginate_query
from app.services.series import get_series_or_404

router = APIRouter(prefix="/series", tags=["series"])


@router.get("/", response_model=PaginatedResponse[SeriesListItemRead])
async def list_series(
    db: DBSession,
    pagination: PaginationDep,
    search: str | None = Query(
        default=None,
        max_length=200,
        description="Filter by title, description, or genre",
    ),
    genre: str | None = Query(
        default=None,
        max_length=100,
        description="Filter by exact genre label (e.g. Drama)",
    ),
):
    from app.services.catalog_search import apply_catalog_genre, apply_catalog_search

    stmt = (
        select(Series)
        .where(Series.is_published.is_(True))
        .order_by(Series.created_at.desc())
    )
    stmt = apply_catalog_search(stmt, Series, search=search)
    stmt = apply_catalog_genre(stmt, Series, genre=genre)
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


@router.get("/{slug}/related", response_model=list[SeriesListItemRead])
async def get_related_series(
    slug: str,
    db: DBSession,
    limit: int = Query(default=8, ge=1, le=24),
):
    from app.services.catalog_related import related_series

    series = await get_series_or_404(db, slug, published_only=True)
    items = await related_series(db, series=series, limit=limit)
    return [SeriesListItemRead.model_validate(item) for item in items]


@router.get("/{slug}", response_model=SeriesRead)
async def get_series(slug: str, db: DBSession, current_user: OptionalUser):
    published_only = not current_user or current_user.role != "admin"
    return await get_series_or_404(db, slug, published_only=published_only)


@router.post("/", response_model=SeriesRead, status_code=201)
async def create_series(data: CreateSeriesBody, db: DBSession, _: AdminUser):
    """Create a series record. Upload the poster separately via /series/{slug}/poster/start."""
    slug = await unique_series_slug(data.title, db)
    series = Series(
        id=uuid.uuid4(),
        slug=slug,
        title=data.title,
        title_km=data.title_km,
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
    series = await get_series_or_404(db, slug)
    poster_key = r2_keys.series_poster_key(series.slug, data.poster_content_type)
    url = storage.generate_presigned_upload_url(poster_key, data.poster_content_type)
    return SeriesPosterStartRead(series_id=series.id, poster_key=poster_key, poster_upload_url=url)


@router.post("/{slug}/banner/start", response_model=SeriesBannerStartRead)
async def start_series_banner_upload(slug: str, data: SeriesBannerStart, db: DBSession, _: AdminUser):
    """Get a presigned URL to upload the series banner directly to R2."""
    series = await get_series_or_404(db, slug)
    banner_key = r2_keys.series_banner_key(series.slug, data.banner_content_type)
    url = storage.generate_presigned_upload_url(banner_key, data.banner_content_type)
    return SeriesBannerStartRead(series_id=series.id, banner_key=banner_key, banner_upload_url=url)


@router.patch("/{slug}", response_model=SeriesRead)
async def update_series(slug: str, data: SeriesUpdate, db: DBSession, _: AdminUser):
    series = await get_series_or_404(db, slug)
    updates = data.model_dump(exclude_unset=True)
    if updates.get("monthly_price_usd") is None:
        updates.pop("monthly_price_usd", None)
    if updates.get("poster_key") or updates.get("banner_key"):
        poster_task = (
            optimize_r2_image(updates["poster_key"], kind="poster")
            if updates.get("poster_key")
            else asyncio.sleep(0, result=None)
        )
        banner_task = (
            optimize_r2_image(updates["banner_key"], kind="banner")
            if updates.get("banner_key")
            else asyncio.sleep(0, result=None)
        )
        poster_key, banner_key = await asyncio.gather(poster_task, banner_task)
        if updates.get("poster_key"):
            updates["poster_key"] = poster_key
        if updates.get("banner_key"):
            updates["banner_key"] = banner_key
    for field, value in updates.items():
        setattr(series, field, value)
    await db.commit()
    await db.refresh(series)
    return series


@router.delete("/{slug}", status_code=204)
async def delete_series(slug: str, db: DBSession, _: AdminUser):
    series = await get_series_or_404(db, slug)
    await delete_series_and_dependencies(db, series.id)
    await db.delete(series)
    await db.commit()


@router.get("/{slug}/episodes", response_model=list[SeasonRead])
async def list_episodes(slug: str, db: DBSession, current_user: OptionalUser):
    """Published episodes for a series (public — used for free-episode discovery on the catalog)."""
    series = await get_series_or_404(db, slug, published_only=True)

    eps_result = await db.execute(
        select(Content)
        .where(Content.series_id == series.id, Content.is_published.is_(True))
        .order_by(Content.season_number, Content.episode_number)
    )
    episodes = eps_result.scalars().all()

    is_admin = current_user is not None and current_user.role == "admin"
    has_sub = current_user is not None and await user_has_active_subscription(
        db, current_user.id
    )

    seasons: dict[int, list[ContentRead]] = {}
    for ep in episodes:
        data = ContentRead.model_validate(ep)
        if not (is_admin or ep.is_free or has_sub):
            data.hls_master_key = None
        seasons.setdefault(ep.season_number or 1, []).append(data)

    return [
        SeasonRead(season_number=sn, episodes=eps)
        for sn, eps in sorted(seasons.items())
    ]


@router.post("/{slug}/episodes/uploads/start", response_model=EpisodeUploadStartRead)
async def start_episode_upload(slug: str, data: EpisodeUploadStart, db: DBSession, _: AdminUser):
    """Initiate a multipart upload for an episode."""
    await get_series_or_404(db, slug)

    content_id = uuid.uuid4()
    episode_slug = await unique_content_slug(
        f"{slug}-s{data.season_number:02d}e{data.episode_number:02d}",
        db,
    )
    source_key = r2_keys.episode_source_key(slug, episode_slug)

    poster_key: str | None = None
    if data.poster_content_type:
        poster_key = r2_keys.episode_poster_key(slug, episode_slug, data.poster_content_type)

    upload = await start_multipart_upload(
        source_key,
        data.video_content_type,
        data.file_size_bytes,
        poster_key=poster_key,
        poster_content_type=data.poster_content_type,
    )

    return EpisodeUploadStartRead(
        content_id=content_id,
        episode_slug=episode_slug,
        source_key=source_key,
        poster_key=poster_key,
        **upload,
    )


@router.get("/{slug}/episodes/uploads/part-url", response_model=PartUrlRead)
async def get_episode_part_url(
    slug: str,
    _: AdminUser,
    source_key: str = Query(..., description="source_key from /episodes/uploads/start"),
    upload_id: str = Query(..., description="upload_id from /episodes/uploads/start"),
    part_number: int = Query(..., ge=1, le=10000, description="1-based chunk index"),
):
    """Return a presigned PUT URL for one episode video chunk."""
    return PartUrlRead(url=presigned_part_url(source_key, upload_id, part_number))


@router.post("/{slug}/episodes/uploads/complete", response_model=ContentRead, status_code=201)
async def complete_episode_upload(slug: str, data: EpisodeUploadComplete, db: DBSession, _: AdminUser):
    """Assemble the uploaded parts, then create the episode record and transcode job."""
    try:
        validate_content_status(data.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    series = await get_series_or_404(db, slug)

    expected_source_key = r2_keys.episode_source_key(slug, data.episode_slug)
    if data.source_key != expected_source_key:
        raise HTTPException(status_code=422, detail="source_key does not match episode_slug")

    if data.poster_key and not r2_keys.is_episode_asset_key(slug, data.episode_slug, data.poster_key):
        raise HTTPException(status_code=422, detail="poster_key does not match episode_slug")

    await complete_multipart_upload(data.source_key, data.upload_id, data.parts)
    await verify_storage_objects_exist(
        data.poster_key,
        missing_detail="Poster upload is not available in storage yet",
    )

    poster_key = await optimize_r2_image(data.poster_key, kind="poster")

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
        poster_key=poster_key,
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
    """Cancel an in-progress episode multipart upload."""
    await abort_multipart_upload(data.source_key, data.upload_id)


async def _get_episode_or_404(db, series: Series, episode_slug: str) -> Content:
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
    return episode


@router.post(
    "/{slug}/episodes/{episode_slug}/assets/start",
    response_model=EpisodeAssetUploadStartRead,
)
async def start_episode_asset_upload(
    slug: str,
    episode_slug: str,
    data: EpisodeAssetUploadStart,
    db: DBSession,
    _: AdminUser,
):
    """Presign replace upload for an existing episode video and/or poster."""
    series = await get_series_or_404(db, slug)
    await _get_episode_or_404(db, series, episode_slug)

    source_key: str | None = None
    video_upload_url: str | None = None
    poster_key: str | None = None
    poster_upload_url: str | None = None

    if data.video_content_type:
        source_key = r2_keys.episode_source_key(slug, episode_slug)
        video_upload_url = storage.generate_presigned_upload_url(
            source_key,
            data.video_content_type,
        )

    if data.poster_content_type:
        poster_key = r2_keys.episode_poster_key(slug, episode_slug, data.poster_content_type)
        poster_upload_url = storage.generate_presigned_upload_url(
            poster_key,
            data.poster_content_type,
        )

    if not source_key and not poster_key:
        raise HTTPException(status_code=422, detail="Choose a video or poster file to replace")

    return EpisodeAssetUploadStartRead(
        source_key=source_key,
        video_upload_url=video_upload_url,
        poster_key=poster_key,
        poster_upload_url=poster_upload_url,
    )


@router.post(
    "/{slug}/episodes/{episode_slug}/assets/complete",
    response_model=ContentRead,
)
async def complete_episode_asset_upload(
    slug: str,
    episode_slug: str,
    data: EpisodeAssetUploadComplete,
    db: DBSession,
    _: AdminUser,
):
    """Finalize episode video/poster replace and queue re-transcode when video changed."""
    series = await get_series_or_404(db, slug)
    episode = await _get_episode_or_404(db, series, episode_slug)

    if data.source_key:
        if data.source_key != r2_keys.episode_source_key(slug, episode_slug):
            raise HTTPException(status_code=422, detail="source_key does not match episode")
        source_exists = await asyncio.get_event_loop().run_in_executor(
            None,
            storage.object_exists,
            data.source_key,
        )
        if not source_exists:
            raise HTTPException(status_code=409, detail="Video upload is not available in storage yet")

        episode.transcode_status = "pending"
        episode.hls_master_key = None
        episode.duration_seconds = None
        db.add(TranscodeJob(content_id=episode.id, source_key=data.source_key))

    if data.poster_key:
        if not r2_keys.is_episode_asset_key(slug, episode_slug, data.poster_key):
            raise HTTPException(status_code=422, detail="poster_key does not match episode")
        poster_exists = await asyncio.get_event_loop().run_in_executor(
            None,
            storage.object_exists,
            data.poster_key,
        )
        if not poster_exists:
            raise HTTPException(status_code=409, detail="Poster upload is not available in storage yet")

        episode.poster_key = await optimize_r2_image(data.poster_key, kind="poster")

    if not data.source_key and not data.poster_key:
        raise HTTPException(status_code=422, detail="No uploaded assets provided")

    await db.commit()
    await db.refresh(episode)
    return episode


@router.patch("/{slug}/episodes/{episode_slug}", response_model=ContentRead)
async def update_episode(
    slug: str, episode_slug: str, data: ContentUpdate, db: DBSession, _: AdminUser
):
    series = await get_series_or_404(db, slug)
    episode = await _get_episode_or_404(db, series, episode_slug)

    updates = data.model_dump(exclude_unset=True)
    if "status" in updates:
        try:
            validate_content_status(updates["status"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        updates.setdefault("is_published", updates["status"] == "published")

    for field, value in updates.items():
        setattr(episode, field, value)

    await db.commit()
    await db.refresh(episode)
    return episode


@router.delete("/{slug}/episodes/{episode_slug}", status_code=204)
async def delete_episode(slug: str, episode_slug: str, db: DBSession, _: AdminUser):
    series = await get_series_or_404(db, slug)
    episode = await _get_episode_or_404(db, series, episode_slug)

    await delete_content_dependencies(db, episode.id)
    await db.delete(episode)
    await db.commit()
