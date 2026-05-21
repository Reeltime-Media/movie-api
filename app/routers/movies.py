"""Movie upload flow (multipart — API server never buffers video bytes):

  1. POST /movies/uploads/start
       → { content_id, upload_id, source_key, part_size, poster_key?, poster_upload_url? }

  2. GET  /movies/uploads/part-url?source_key=…&upload_id=…&part_number=N
       → { url }   (presigned PUT — client uploads the chunk directly to R2)

  3. POST /movies/uploads/complete
       → ContentRead   (completes multipart upload + creates DB record + queues transcode)

  4. POST /movies/uploads/abort
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
from app.models.transcode_job import TranscodeJob
from app.schemas.content import ContentRead, ContentUpdate
from app.services import storage
from app.services.content_delete import delete_transcode_jobs_for_content

router = APIRouter(prefix="/movies", tags=["movies"])

_VALID_STATUSES = {"draft", "review", "scheduled", "published"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


async def _unique_slug(base: str, db) -> str:
    slug = _slugify(base)
    existing = await db.execute(select(Content).where(Content.slug == slug))
    if not existing.scalar_one_or_none():
        return slug
    return f"{slug}-{uuid.uuid4().hex[:6]}"


# ── Schemas ───────────────────────────────────────────────────────────────────

class MovieUploadStart(BaseModel):
    video_content_type: str = "video/mp4"
    poster_content_type: str | None = None


class MovieUploadStartRead(BaseModel):
    content_id: uuid.UUID
    upload_id: str          # R2 multipart upload ID
    source_key: str
    part_size: int          # recommended bytes per chunk (50 MB)
    poster_key: str | None = None
    poster_upload_url: str | None = None


class PartUrlRead(BaseModel):
    url: str


class MultipartPart(BaseModel):
    part_number: int
    etag: str


class MovieUploadComplete(BaseModel):
    content_id: uuid.UUID
    source_key: str
    upload_id: str
    parts: list[MultipartPart]   # ETags from each chunk upload response
    title: str
    price_usd: Decimal
    description: str | None = None
    genres: list[str] = []
    release_year: int | None = None
    rating: Decimal | None = None
    runtime: str | None = None
    status: str = "draft"
    trailer_url: str | None = None
    poster_key: str | None = None


class MovieUploadAbort(BaseModel):
    source_key: str
    upload_id: str


# ── Upload endpoints ───────────────────────────────────────────────────────────

@router.post("/uploads/start", response_model=MovieUploadStartRead)
async def start_movie_upload(data: MovieUploadStart, _: AdminUser):
    """Initiate a multipart upload. Returns upload_id + part_size.

    The client must split the video file into chunks of `part_size` bytes and
    PUT each chunk to R2 using the URL from /uploads/part-url. The API server
    never receives any video bytes.
    """
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
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }.get(data.poster_content_type, "jpg")
        poster_key = f"posters/{content_id}.{ext}"
        poster_upload_url = storage.generate_presigned_upload_url(
            poster_key, data.poster_content_type
        )

    return MovieUploadStartRead(
        content_id=content_id,
        upload_id=upload_id,
        source_key=source_key,
        part_size=storage.MULTIPART_PART_SIZE,
        poster_key=poster_key,
        poster_upload_url=poster_upload_url,
    )


@router.get("/uploads/part-url", response_model=PartUrlRead)
async def get_part_url(
    _: AdminUser,
    source_key: str = Query(..., description="source_key from /uploads/start"),
    upload_id: str = Query(..., description="upload_id from /uploads/start"),
    part_number: int = Query(..., ge=1, le=10000, description="1-based chunk index"),
):
    """Return a presigned PUT URL for one video chunk.

    The client calls this once per part, then PUTs the raw bytes directly to
    R2. Save the ETag from each response header — it is required for /uploads/complete.
    """
    url = storage.generate_presigned_part_url(source_key, upload_id, part_number)
    return PartUrlRead(url=url)


@router.post("/uploads/complete", response_model=ContentRead, status_code=201)
async def complete_movie_upload(data: MovieUploadComplete, db: DBSession, _: AdminUser):
    """Assemble the uploaded parts, then create the content record and transcode job."""
    if data.status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUSES)}")

    expected_source_key = f"raw/{data.content_id}.mp4"
    if data.source_key != expected_source_key:
        raise HTTPException(status_code=422, detail="source_key does not match content_id")

    if not data.parts:
        raise HTTPException(status_code=422, detail="parts list is empty")

    loop = asyncio.get_event_loop()

    # Complete the multipart upload — R2 assembles the parts into the final object.
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

    slug = await _unique_slug(data.title, db)
    movie = Content(
        id=data.content_id,
        type="single",
        slug=slug,
        title=data.title,
        description=data.description,
        genres=data.genres,
        release_year=data.release_year,
        rating=data.rating,
        runtime=data.runtime,
        price_usd=data.price_usd,
        poster_key=data.poster_key,
        trailer_url=data.trailer_url,
        status=data.status,
        is_published=(data.status == "published"),
        transcode_status="pending",
    )
    db.add(movie)
    db.add(TranscodeJob(content_id=data.content_id, source_key=data.source_key))

    await db.commit()
    await db.refresh(movie)
    return movie


@router.post("/uploads/abort", status_code=204)
async def abort_movie_upload(data: MovieUploadAbort, _: AdminUser):
    """Cancel an in-progress multipart upload and free the stored parts on R2."""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, storage.abort_multipart_upload, data.source_key, data.upload_id
        )
    except Exception:
        pass  # already completed or never existed — not an error from the caller's perspective


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[ContentRead])
async def list_movies(db: DBSession):
    result = await db.execute(
        select(Content).where(Content.type == "single", Content.is_published.is_(True))
    )
    return result.scalars().all()


@router.get("/{slug}", response_model=ContentRead)
async def get_movie(slug: str, db: DBSession, _: CurrentUser):
    result = await db.execute(
        select(Content).where(Content.slug == slug, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")
    return movie


@router.patch("/{slug}", response_model=ContentRead)
async def update_movie(slug: str, data: ContentUpdate, db: DBSession, _: AdminUser):
    result = await db.execute(
        select(Content).where(Content.slug == slug, Content.type == "single")
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise NotFoundError("Movie not found")

    updates = data.model_dump(exclude_unset=True)
    if "status" in updates:
        if updates["status"] not in _VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUSES)}")
        updates.setdefault("is_published", updates["status"] == "published")

    for field, value in updates.items():
        setattr(movie, field, value)

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
    await delete_transcode_jobs_for_content(db, movie.id)
    await db.delete(movie)
    await db.commit()
