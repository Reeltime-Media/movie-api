import asyncio
import io
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, CurrentUser, DBSession
from app.models.content import Content
from app.models.transcode_job import TranscodeJob
from app.schemas.content import ContentRead, ContentUpdate
from app.services import storage

router = APIRouter(prefix="/movies", tags=["movies"])

_VALID_STATUSES = {"draft", "review", "scheduled", "published"}


class MovieUploadStart(BaseModel):
    video_content_type: str = "video/mp4"
    poster_content_type: str | None = None


class MovieUploadStartRead(BaseModel):
    content_id: uuid.UUID
    source_key: str
    video_upload_url: str
    poster_key: str | None = None
    poster_upload_url: str | None = None


class MovieUploadComplete(BaseModel):
    content_id: uuid.UUID
    source_key: str
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


@router.post("/uploads/start", response_model=MovieUploadStartRead)
async def start_movie_upload(data: MovieUploadStart, _: AdminUser):
    content_id = uuid.uuid4()
    source_key = f"raw/{content_id}.mp4"
    poster_key: str | None = None
    poster_upload_url: str | None = None

    if data.poster_content_type:
        poster_ext = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }.get(data.poster_content_type, "jpg")
        poster_key = f"posters/{content_id}.{poster_ext}"
        poster_upload_url = storage.generate_presigned_upload_url(
            poster_key,
            data.poster_content_type,
        )

    return MovieUploadStartRead(
        content_id=content_id,
        source_key=source_key,
        video_upload_url=storage.generate_presigned_upload_url(
            source_key,
            data.video_content_type or "video/mp4",
        ),
        poster_key=poster_key,
        poster_upload_url=poster_upload_url,
    )


@router.post("/uploads/complete", response_model=ContentRead, status_code=201)
async def complete_movie_upload(data: MovieUploadComplete, db: DBSession, _: AdminUser):
    if data.status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUSES)}")

    expected_source_key = f"raw/{data.content_id}.mp4"
    if data.source_key != expected_source_key:
        raise HTTPException(status_code=422, detail="source_key does not match content_id")

    loop = asyncio.get_event_loop()
    source_exists = await loop.run_in_executor(None, storage.object_exists, data.source_key)
    if not source_exists:
        raise HTTPException(status_code=409, detail="Video upload is not available in storage yet")

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


@router.get("/", response_model=list[ContentRead])
async def list_movies(db: DBSession, _: CurrentUser):
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


@router.post("/", response_model=ContentRead, status_code=201)
async def create_movie(
    db: DBSession,
    _: AdminUser,
    title: Annotated[str, Form()],
    price_usd: Annotated[str, Form()],
    video: Annotated[UploadFile, File(description="Raw video file (mp4 recommended)")],
    description: Annotated[str | None, Form()] = None,
    genres: Annotated[str | None, Form(description='JSON array e.g. ["Action","Drama"]')] = None,
    release_year: Annotated[int | None, Form()] = None,
    rating: Annotated[str | None, Form(description="Decimal e.g. 8.7")] = None,
    runtime: Annotated[str | None, Form(description='e.g. "1h 42m"')] = None,
    status: Annotated[str, Form()] = "draft",
    trailer_url: Annotated[str | None, Form(description="YouTube URL for the trailer")] = None,
    poster: Annotated[UploadFile | None, File(description="Poster image")] = None,
):
    if status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUSES)}")

    try:
        parsed_price = Decimal(price_usd)
    except InvalidOperation:
        raise HTTPException(status_code=422, detail="Invalid price_usd value")

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

    slug = await _unique_slug(title, db)
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

    movie = Content(
        id=content_id,
        type="single",
        slug=slug,
        title=title,
        description=description,
        genres=parsed_genres,
        release_year=release_year,
        rating=parsed_rating,
        runtime=runtime,
        price_usd=parsed_price,
        poster_key=poster_key,
        trailer_url=trailer_url,
        status=status,
        is_published=(status == "published"),
        transcode_status="pending",
    )
    db.add(movie)
    db.add(TranscodeJob(content_id=content_id, source_key=source_key))

    await db.commit()
    await db.refresh(movie)
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
    await db.delete(movie)
    await db.commit()
