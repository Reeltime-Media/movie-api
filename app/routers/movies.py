"""Movie upload flow (multipart — API server never buffers video bytes):

  1. POST /movies/uploads/start  (requires title + file_size_bytes)
       → { content_id, slug, upload_id, source_key, part_size, part_urls[], poster_key?, poster_upload_url? }

  2. GET  /movies/uploads/part-url?source_key=…&upload_id=…&part_number=N
       → { url }   (optional fallback — start returns all part URLs in one response)

  3. POST /movies/uploads/complete
       → ContentRead   (completes multipart upload + creates DB record + queues transcode)

  4. POST /movies/uploads/abort
       → 204           (frees partial uploads on cancel / error)
"""

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.core.content_status import validate_content_status
from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, DBSession, OptionalUser
from app.models.content import Content
from app.models.transcode_job import TranscodeJob
from app.schemas.content import ContentListItemRead, ContentRead, ContentUpdate
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.schemas.upload import (
    MovieUploadComplete,
    MovieUploadStart,
    MovieUploadStartRead,
    MultipartUploadAbort,
    PartUrlRead,
)
from app.services import r2_keys
from app.services.content_access import user_can_access_content
from app.services.content_delete import delete_content_dependencies
from app.services.content_publish import ensure_movie_publishable
from app.services.content_slug import unique_content_slug
from app.services.content_upload import (
    abort_multipart_upload,
    complete_multipart_upload,
    presigned_part_url,
    start_multipart_upload,
    verify_storage_objects_exist,
)
from app.services.pagination import paginate_query
from app.services.runtime import apply_runtime_minutes

router = APIRouter(prefix="/movies", tags=["movies"])


@router.post("/uploads/start", response_model=MovieUploadStartRead)
async def start_movie_upload(data: MovieUploadStart, db: DBSession, _: AdminUser):
    """Initiate a multipart upload. Returns upload_id + part_size.

    The client must split the video file into chunks of `part_size` bytes and
    PUT each chunk to R2 using the URL from /uploads/part-url. The API server
    never receives any video bytes.
    """
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required")

    content_id = uuid.uuid4()
    slug = await unique_content_slug(title, db)
    source_key = r2_keys.movie_source_key(slug)

    poster_key: str | None = None
    if data.poster_content_type:
        poster_key = r2_keys.movie_poster_key(slug, data.poster_content_type)

    banner_key: str | None = None
    if data.banner_content_type:
        banner_key = r2_keys.movie_banner_key(slug, data.banner_content_type)

    upload = await start_multipart_upload(
        source_key,
        data.video_content_type,
        data.file_size_bytes,
        poster_key=poster_key,
        poster_content_type=data.poster_content_type,
        banner_key=banner_key,
        banner_content_type=data.banner_content_type,
    )

    return MovieUploadStartRead(
        content_id=content_id,
        slug=slug,
        source_key=source_key,
        poster_key=poster_key,
        banner_key=banner_key,
        **upload,
    )


@router.get("/uploads/part-url", response_model=PartUrlRead)
async def get_part_url(
    _: AdminUser,
    source_key: str = Query(..., description="source_key from /uploads/start"),
    upload_id: str = Query(..., description="upload_id from /uploads/start"),
    part_number: int = Query(..., ge=1, le=10000, description="1-based chunk index"),
):
    """Return a presigned PUT URL for one video chunk."""
    return PartUrlRead(url=presigned_part_url(source_key, upload_id, part_number))


@router.post("/uploads/complete", response_model=ContentRead, status_code=201)
async def complete_movie_upload(data: MovieUploadComplete, db: DBSession, _: AdminUser):
    """Assemble the uploaded parts, then create the content record and transcode job."""
    try:
        validate_content_status(data.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    expected_source_key = r2_keys.movie_source_key(data.slug)
    if data.source_key != expected_source_key:
        raise HTTPException(status_code=422, detail="source_key does not match slug")

    if data.poster_key and not r2_keys.is_movie_asset_key(data.slug, data.poster_key):
        raise HTTPException(status_code=422, detail="poster_key does not match slug")

    if data.banner_key and not r2_keys.is_movie_asset_key(data.slug, data.banner_key):
        raise HTTPException(status_code=422, detail="banner_key does not match slug")

    if data.status == "published" and not data.poster_key:
        raise HTTPException(status_code=422, detail="A poster is required before publishing.")

    await complete_multipart_upload(data.source_key, data.upload_id, data.parts)
    await verify_storage_objects_exist(
        data.poster_key,
        missing_detail="Poster upload is not available in storage yet",
    )
    await verify_storage_objects_exist(
        data.banner_key,
        missing_detail="Banner upload is not available in storage yet",
    )

    movie = Content(
        id=data.content_id,
        type="single",
        slug=data.slug,
        title=data.title,
        description=data.description,
        genres=data.genres,
        release_year=data.release_year,
        rating=data.rating,
        price_usd=data.price_usd,
        poster_key=data.poster_key,
        banner_key=data.banner_key,
        trailer_url=data.trailer_url,
        status=data.status,
        is_published=(data.status == "published"),
        transcode_status="pending",
    )
    apply_runtime_minutes(movie, data.runtime_minutes)
    db.add(movie)
    db.add(TranscodeJob(content_id=data.content_id, source_key=data.source_key))

    if data.status == "published":
        await ensure_movie_publishable(db, movie)

    await db.commit()
    await db.refresh(movie)
    return movie


@router.post("/uploads/abort", status_code=204)
async def abort_movie_upload(data: MultipartUploadAbort, _: AdminUser):
    """Cancel an in-progress multipart upload and free the stored parts on R2."""
    await abort_multipart_upload(data.source_key, data.upload_id)


@router.get("/", response_model=PaginatedResponse[ContentListItemRead])
async def list_movies(
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
        description="Filter by exact genre label (e.g. Action)",
    ),
):
    from app.services.catalog_search import apply_catalog_genre, apply_catalog_search

    stmt = (
        select(Content)
        .where(Content.type == "single", Content.is_published.is_(True))
        .order_by(Content.created_at.desc())
    )
    stmt = apply_catalog_search(stmt, Content, search=search)
    stmt = apply_catalog_genre(stmt, Content, genre=genre)
    items, total = await paginate_query(
        db,
        stmt,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return build_paginated_response(
        [ContentListItemRead.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{slug}", response_model=ContentRead)
async def get_movie(slug: str, db: DBSession, current_user: OptionalUser):
    stmt = select(Content).where(Content.slug == slug, Content.type == "single")
    if not current_user or current_user.role != "admin":
        stmt = stmt.where(Content.is_published.is_(True))
    result = await db.execute(stmt)
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")
    data = ContentRead.model_validate(movie)
    if not (current_user and await user_can_access_content(db, current_user, movie)):
        data.hls_master_key = None
    return data


@router.patch("/{slug}", response_model=ContentRead)
async def update_movie(slug: str, data: ContentUpdate, db: DBSession, _: AdminUser):
    result = await db.execute(
        select(Content).where(Content.slug == slug, Content.type == "single")
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
        updates.setdefault("is_published", updates["status"] == "published")

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


@router.delete("/{slug}", status_code=204)
async def delete_movie(slug: str, db: DBSession, _: AdminUser):
    result = await db.execute(
        select(Content).where(Content.slug == slug, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")
    await delete_content_dependencies(db, movie.id)
    await db.delete(movie)
    await db.commit()
