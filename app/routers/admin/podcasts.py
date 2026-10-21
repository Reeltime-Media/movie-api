"""Admin CRUD + asset upload for standalone horror podcasts."""

import asyncio
import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.content_status import validate_content_status
from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.content import Content
from app.schemas.admin import (
    AdminPodcastCreate,
    PodcastAssetUploadComplete,
    PodcastAssetUploadStart,
    PodcastAssetUploadStartRead,
)
from app.schemas.content import AdminContentRead, ContentRead, ContentUpdate
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services import r2_keys, storage
from app.services.admin.helpers import purchase_counts_for_content, watch_counts_for_content
from app.services.content_delete import delete_content_dependencies
from app.services.content_publish import ensure_podcast_publishable
from app.services.content_slug import unique_content_slug
from app.services.image_process import optimize_r2_image
from app.services.pagination import paginate_query
from app.services.runtime import apply_runtime_minutes

router = APIRouter()

_AUDIO_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/x-m4a",
    "audio/m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/aac",
}


def _validate_audio_content_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in _AUDIO_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Audio must be mp3, m4a, wav, or aac",
        )
    return normalized


@router.post("/podcasts", response_model=ContentRead, status_code=201)
async def create_admin_podcast_draft(data: AdminPodcastCreate, db: DBSession, _: AdminUser):
    slug = await unique_content_slug(data.title, db)
    podcast = Content(
        id=uuid.uuid4(),
        type="podcast",
        slug=slug,
        title=data.title,
        title_km=data.title_km,
        description=data.description,
        genres=data.genres or ["Horror"],
        release_year=data.release_year,
        # Podcasts are plan-included (or free) — never à-la-carte priced.
        price_usd=Decimal("0"),
        is_free=data.is_free,
        status="draft",
        is_published=False,
        transcode_status="pending",
    )
    apply_runtime_minutes(podcast, data.runtime_minutes)
    db.add(podcast)
    await db.commit()
    await db.refresh(podcast)
    return podcast


@router.get("/podcasts", response_model=PaginatedResponse[AdminContentRead])
async def list_admin_podcasts(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
):
    stmt = select(Content).where(Content.type == "podcast").order_by(Content.created_at.desc())
    items, total = await paginate_query(
        db, stmt, page=pagination.page, page_size=pagination.page_size
    )
    content_ids = [p.id for p in items]
    watch_counts = await watch_counts_for_content(db, content_ids)
    purchase_counts = await purchase_counts_for_content(db, content_ids)
    return build_paginated_response(
        [
            AdminContentRead(
                **ContentRead.model_validate(p).model_dump(),
                watch_count=watch_counts.get(p.id, 0),
                purchase_count=purchase_counts.get(p.id, 0),
            )
            for p in items
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/podcasts/{podcast_id}", response_model=AdminContentRead)
async def get_admin_podcast(podcast_id: uuid.UUID, db: DBSession, _: AdminUser):
    result = await db.execute(
        select(Content).where(Content.id == podcast_id, Content.type == "podcast")
    )
    podcast = result.scalar_one_or_none()
    if not podcast:
        raise NotFoundError("Podcast not found")
    watch_counts = await watch_counts_for_content(db, [podcast.id])
    purchase_counts = await purchase_counts_for_content(db, [podcast.id])
    return AdminContentRead(
        **ContentRead.model_validate(podcast).model_dump(),
        watch_count=watch_counts.get(podcast.id, 0),
        purchase_count=purchase_counts.get(podcast.id, 0),
    )


@router.patch("/podcasts/{podcast_id}", response_model=ContentRead)
async def update_admin_podcast(
    podcast_id: uuid.UUID,
    data: ContentUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(Content).where(Content.id == podcast_id, Content.type == "podcast")
    )
    podcast = result.scalar_one_or_none()
    if not podcast:
        raise NotFoundError("Podcast not found")

    updates = data.model_dump(exclude_unset=True)
    runtime_minutes = updates.pop("runtime_minutes", None)
    # Ignore client price — podcasts stay plan-included / free only.
    updates.pop("price_usd", None)
    podcast.price_usd = Decimal("0")
    if "status" in updates:
        try:
            validate_content_status(updates["status"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        updates["is_published"] = updates["status"] == "published"

    for field, value in updates.items():
        setattr(podcast, field, value)

    if "runtime_minutes" in data.model_fields_set:
        if runtime_minutes is None:
            podcast.duration_seconds = None
            podcast.runtime = None
        else:
            apply_runtime_minutes(podcast, runtime_minutes)

    if podcast.status == "published":
        ensure_podcast_publishable(podcast)

    await db.commit()
    await db.refresh(podcast)
    return podcast


@router.post("/podcasts/{podcast_id}/assets/start", response_model=PodcastAssetUploadStartRead)
async def start_admin_podcast_asset_upload(
    podcast_id: uuid.UUID,
    data: PodcastAssetUploadStart,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(Content).where(Content.id == podcast_id, Content.type == "podcast")
    )
    podcast = result.scalar_one_or_none()
    if not podcast:
        raise NotFoundError("Podcast not found")

    audio_key: str | None = None
    audio_upload_url: str | None = None
    poster_key: str | None = None
    poster_upload_url: str | None = None

    if data.audio_content_type:
        audio_type = _validate_audio_content_type(data.audio_content_type)
        audio_key = r2_keys.podcast_audio_key(podcast.slug, audio_type)
        audio_upload_url = storage.generate_presigned_upload_url(audio_key, audio_type)

    if data.poster_content_type:
        poster_key = r2_keys.podcast_poster_key(podcast.slug, data.poster_content_type)
        poster_upload_url = storage.generate_presigned_upload_url(
            poster_key,
            data.poster_content_type,
        )

    if not audio_key and not poster_key:
        raise HTTPException(status_code=422, detail="Choose an audio or cover file to upload")

    return PodcastAssetUploadStartRead(
        audio_key=audio_key,
        audio_upload_url=audio_upload_url,
        poster_key=poster_key,
        poster_upload_url=poster_upload_url,
    )


@router.post("/podcasts/{podcast_id}/assets/complete", response_model=ContentRead)
async def complete_admin_podcast_asset_upload(
    podcast_id: uuid.UUID,
    data: PodcastAssetUploadComplete,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(
        select(Content).where(Content.id == podcast_id, Content.type == "podcast")
    )
    podcast = result.scalar_one_or_none()
    if not podcast:
        raise NotFoundError("Podcast not found")

    if data.audio_key:
        if not r2_keys.is_podcast_asset_key(podcast.slug, data.audio_key):
            raise HTTPException(status_code=422, detail="audio_key does not match podcast")
        audio_exists = await asyncio.get_event_loop().run_in_executor(
            None,
            storage.object_exists,
            data.audio_key,
        )
        if not audio_exists:
            raise HTTPException(
                status_code=409, detail="Audio upload is not available in storage yet"
            )
        podcast.audio_key = data.audio_key
        podcast.transcode_status = "ready"

    if data.poster_key:
        if not r2_keys.is_podcast_asset_key(podcast.slug, data.poster_key):
            raise HTTPException(status_code=422, detail="poster_key does not match podcast")
        poster_exists = await asyncio.get_event_loop().run_in_executor(
            None,
            storage.object_exists,
            data.poster_key,
        )
        if not poster_exists:
            raise HTTPException(
                status_code=409, detail="Cover upload is not available in storage yet"
            )
        poster_key = await optimize_r2_image(data.poster_key, kind="poster")
        podcast.poster_key = poster_key

    if not data.audio_key and not data.poster_key:
        raise HTTPException(status_code=422, detail="No uploaded assets provided")

    await db.commit()
    await db.refresh(podcast)
    return podcast


@router.delete("/podcasts/{podcast_id}", status_code=204)
async def delete_admin_podcast(podcast_id: uuid.UUID, db: DBSession, _: AdminUser):
    result = await db.execute(
        select(Content).where(Content.id == podcast_id, Content.type == "podcast")
    )
    podcast = result.scalar_one_or_none()
    if not podcast:
        raise NotFoundError("Podcast not found")
    await delete_content_dependencies(db, podcast_id)
    await db.delete(podcast)
    await db.commit()
