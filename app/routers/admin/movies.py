import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.content_status import validate_content_status
from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.content import Content
from app.models.transcode_job import TranscodeJob
from app.schemas.admin import (
    AdminMovieCreate,
    MovieAssetUploadComplete,
    MovieAssetUploadStart,
    MovieAssetUploadStartRead,
)
from app.schemas.content import AdminContentRead, ContentRead, ContentUpdate
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services import r2_keys, storage
from app.services.admin.helpers import purchase_counts_for_content, watch_counts_for_content
from app.services.content_delete import delete_content_dependencies
from app.services.content_publish import ensure_movie_publishable
from app.services.content_slug import unique_content_slug
from app.services.image_process import optimize_r2_image
from app.services.pagination import paginate_query
from app.services.runtime import apply_runtime_minutes

router = APIRouter()


@router.post("/movies", response_model=ContentRead, status_code=201)
async def create_admin_movie_draft(data: AdminMovieCreate, db: DBSession, _: AdminUser):
    """Create a movie record without video (draft). Upload assets later from movie edit."""
    slug = await unique_content_slug(data.title, db)
    movie = Content(
        id=uuid.uuid4(),
        type="single",
        slug=slug,
        title=data.title,
        title_km=data.title_km,
        description=data.description,
        genres=data.genres,
        release_year=data.release_year,
        rating=data.rating,
        price_usd=data.price_usd,
        trailer_url=data.trailer_url,
        status="draft",
        is_published=False,
        transcode_status="pending",
    )
    apply_runtime_minutes(movie, data.runtime_minutes)
    db.add(movie)
    await db.commit()
    await db.refresh(movie)
    return movie


@router.get("/movies", response_model=PaginatedResponse[AdminContentRead])
async def list_admin_movies(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
):
    stmt = (
        select(Content)
        .where(Content.type == "single")
        .order_by(Content.created_at.desc())
    )
    items, total = await paginate_query(
        db, stmt, page=pagination.page, page_size=pagination.page_size
    )
    content_ids = [m.id for m in items]
    watch_counts = await watch_counts_for_content(db, content_ids)
    purchase_counts = await purchase_counts_for_content(db, content_ids)
    return build_paginated_response(
        [
            AdminContentRead(
                **ContentRead.model_validate(m).model_dump(),
                watch_count=watch_counts.get(m.id, 0),
                purchase_count=purchase_counts.get(m.id, 0),
            )
            for m in items
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/movies/{movie_id}", response_model=AdminContentRead)
async def get_admin_movie(movie_id: uuid.UUID, db: DBSession, _: AdminUser):
    result = await db.execute(
        select(Content).where(Content.id == movie_id, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")
    watch_counts = await watch_counts_for_content(db, [movie.id])
    purchase_counts = await purchase_counts_for_content(db, [movie.id])
    return AdminContentRead(
        **ContentRead.model_validate(movie).model_dump(),
        watch_count=watch_counts.get(movie.id, 0),
        purchase_count=purchase_counts.get(movie.id, 0),
    )


@router.patch("/movies/{movie_id}", response_model=ContentRead)
async def update_admin_movie(
    movie_id: uuid.UUID,
    data: ContentUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(Content).where(Content.id == movie_id, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")

    updates = data.model_dump(exclude_unset=True)
    runtime_minutes = updates.pop("runtime_minutes", None)
    if "status" in updates:
        try:
            validate_content_status(updates["status"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        updates["is_published"] = updates["status"] == "published"

    for field, value in updates.items():
        setattr(movie, field, value)

    if "runtime_minutes" in data.model_fields_set:
        if runtime_minutes is None:
            movie.duration_seconds = None
            movie.runtime = None
        else:
            apply_runtime_minutes(movie, runtime_minutes)

    if movie.status == "published":
        await ensure_movie_publishable(db, movie)

    await db.commit()
    await db.refresh(movie)
    return movie


@router.post("/movies/{movie_id}/assets/start", response_model=MovieAssetUploadStartRead)
async def start_admin_movie_asset_upload(
    movie_id: uuid.UUID,
    data: MovieAssetUploadStart,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(Content).where(Content.id == movie_id, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")

    source_key: str | None = None
    video_upload_url: str | None = None
    poster_key: str | None = None
    poster_upload_url: str | None = None
    banner_key: str | None = None
    banner_upload_url: str | None = None

    if data.video_content_type:
        source_key = r2_keys.movie_source_key(movie.slug)
        video_upload_url = storage.generate_presigned_upload_url(
            source_key,
            data.video_content_type,
        )

    if data.poster_content_type:
        poster_key = r2_keys.movie_poster_key(movie.slug, data.poster_content_type)
        poster_upload_url = storage.generate_presigned_upload_url(
            poster_key,
            data.poster_content_type,
        )

    if data.banner_content_type:
        banner_key = r2_keys.movie_banner_key(movie.slug, data.banner_content_type)
        banner_upload_url = storage.generate_presigned_upload_url(
            banner_key,
            data.banner_content_type,
        )

    if not source_key and not poster_key and not banner_key:
        raise HTTPException(status_code=422, detail="Choose a video, poster, or banner file to replace")

    return MovieAssetUploadStartRead(
        source_key=source_key,
        video_upload_url=video_upload_url,
        poster_key=poster_key,
        poster_upload_url=poster_upload_url,
        banner_key=banner_key,
        banner_upload_url=banner_upload_url,
    )


@router.post("/movies/{movie_id}/assets/complete", response_model=ContentRead)
async def complete_admin_movie_asset_upload(
    movie_id: uuid.UUID,
    data: MovieAssetUploadComplete,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(Content).where(Content.id == movie_id, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")

    if data.source_key:
        if data.source_key != r2_keys.movie_source_key(movie.slug):
            raise HTTPException(status_code=422, detail="source_key does not match movie")
        source_exists = await asyncio.get_event_loop().run_in_executor(
            None,
            storage.object_exists,
            data.source_key,
        )
        if not source_exists:
            raise HTTPException(status_code=409, detail="Video upload is not available in storage yet")

        movie.transcode_status = "pending"
        movie.hls_master_key = None
        movie.duration_seconds = None
        db.add(TranscodeJob(content_id=movie.id, source_key=data.source_key))

    if data.poster_key:
        if not r2_keys.is_movie_asset_key(movie.slug, data.poster_key):
            raise HTTPException(status_code=422, detail="poster_key does not match movie")
        poster_exists = await asyncio.get_event_loop().run_in_executor(
            None,
            storage.object_exists,
            data.poster_key,
        )
        if not poster_exists:
            raise HTTPException(status_code=409, detail="Poster upload is not available in storage yet")

        movie.poster_key = await optimize_r2_image(data.poster_key, kind="poster")

    if data.banner_key:
        if not r2_keys.is_movie_asset_key(movie.slug, data.banner_key):
            raise HTTPException(status_code=422, detail="banner_key does not match movie")
        banner_exists = await asyncio.get_event_loop().run_in_executor(
            None,
            storage.object_exists,
            data.banner_key,
        )
        if not banner_exists:
            raise HTTPException(status_code=409, detail="Banner upload is not available in storage yet")

        movie.banner_key = await optimize_r2_image(data.banner_key, kind="banner")

    if not data.source_key and not data.poster_key and not data.banner_key:
        raise HTTPException(status_code=422, detail="No uploaded assets provided")

    await db.commit()
    await db.refresh(movie)
    return movie


@router.delete("/movies/{movie_id}", status_code=204)
async def delete_admin_movie(movie_id: uuid.UUID, db: DBSession, _: AdminUser):
    result = await db.execute(
        select(Content).where(Content.id == movie_id, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")
    await delete_content_dependencies(db, movie_id)
    await db.delete(movie)
    await db.commit()
