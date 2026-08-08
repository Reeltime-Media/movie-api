import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.tv_channel import TVChannel
from app.schemas.channel import (
    TVChannelCreate,
    TVChannelLogoUploadComplete,
    TVChannelLogoUploadStart,
    TVChannelLogoUploadStartRead,
    TVChannelRead,
    TVChannelUpdate,
)
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services import live_client, r2_keys, storage
from app.services.content_slug import slugify
from app.services.pagination import paginate_query

router = APIRouter(prefix="/tv-channels")


async def _unique_channel_slug(base: str, db) -> str:
    slug = slugify(base)
    existing = await db.execute(select(TVChannel).where(TVChannel.slug == slug))
    if not existing.scalar_one_or_none():
        return slug
    return f"{slug}-{uuid.uuid4().hex[:6]}"


async def _get_channel_or_404(db, channel_id: uuid.UUID) -> TVChannel:
    result = await db.execute(select(TVChannel).where(TVChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise NotFoundError("Channel not found")
    return channel


@router.post("", response_model=TVChannelRead, status_code=201)
async def create_channel(data: TVChannelCreate, db: DBSession, _: AdminUser):
    slug = await _unique_channel_slug(data.name, db)
    channel = TVChannel(
        id=uuid.uuid4(),
        slug=slug,
        name=data.name,
        description=data.description,
        source_url=data.source_url,
        is_free=data.is_free,
        status="offline",
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.get("", response_model=PaginatedResponse[TVChannelRead])
async def list_channels(db: DBSession, _: AdminUser, pagination: PaginationDep):
    stmt = select(TVChannel).order_by(TVChannel.sort_order, TVChannel.created_at.desc())
    items, total = await paginate_query(
        db, stmt, page=pagination.page, page_size=pagination.page_size
    )
    return build_paginated_response(
        items, total=total, page=pagination.page, page_size=pagination.page_size
    )


@router.get("/{channel_id}", response_model=TVChannelRead)
async def get_channel(channel_id: uuid.UUID, db: DBSession, _: AdminUser):
    return await _get_channel_or_404(db, channel_id)


@router.patch("/{channel_id}", response_model=TVChannelRead)
async def update_channel(
    channel_id: uuid.UUID, data: TVChannelUpdate, db: DBSession, _: AdminUser
):
    channel = await _get_channel_or_404(db, channel_id)
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(channel, field, value)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(channel_id: uuid.UUID, db: DBSession, _: AdminUser):
    channel = await _get_channel_or_404(db, channel_id)
    if channel.status in ("live", "starting"):
        await live_client.stop_channel(str(channel.id))
    await db.delete(channel)
    await db.commit()


@router.post("/{channel_id}/start", response_model=TVChannelRead)
async def start_channel(channel_id: uuid.UUID, db: DBSession, _: AdminUser):
    channel = await _get_channel_or_404(db, channel_id)
    result = await live_client.start_channel(str(channel.id), channel.source_url)
    channel.status = result.get("status", "starting")
    channel.hls_playback_url = result.get("hls_url") or channel.hls_playback_url
    channel.status_error = None
    await db.commit()
    await db.refresh(channel)
    return channel


@router.post("/{channel_id}/stop", response_model=TVChannelRead)
async def stop_channel(channel_id: uuid.UUID, db: DBSession, _: AdminUser):
    channel = await _get_channel_or_404(db, channel_id)
    result = await live_client.stop_channel(str(channel.id))
    channel.status = result.get("status", "offline")
    channel.status_error = None
    await db.commit()
    await db.refresh(channel)
    return channel


@router.get("/{channel_id}/status", response_model=TVChannelRead)
async def refresh_channel_status(channel_id: uuid.UUID, db: DBSession, _: AdminUser):
    """Poll the live service and sync its reported state onto the channel row."""
    channel = await _get_channel_or_404(db, channel_id)
    result = await live_client.get_channel_status(str(channel.id))
    channel.status = result.get("status", channel.status)
    if result.get("hls_url"):
        channel.hls_playback_url = result["hls_url"]
    channel.status_error = result.get("error")
    await db.commit()
    await db.refresh(channel)
    return channel


@router.post("/{channel_id}/logo/start", response_model=TVChannelLogoUploadStartRead)
async def start_channel_logo_upload(
    channel_id: uuid.UUID, data: TVChannelLogoUploadStart, db: DBSession, _: AdminUser
):
    channel = await _get_channel_or_404(db, channel_id)
    logo_key = r2_keys.tv_channel_logo_key(channel.slug, data.content_type)
    upload_url = storage.generate_presigned_upload_url(logo_key, data.content_type)
    return TVChannelLogoUploadStartRead(logo_key=logo_key, upload_url=upload_url)


@router.post("/{channel_id}/logo/complete", response_model=TVChannelRead)
async def complete_channel_logo_upload(
    channel_id: uuid.UUID, data: TVChannelLogoUploadComplete, db: DBSession, _: AdminUser
):
    channel = await _get_channel_or_404(db, channel_id)
    if not r2_keys.is_tv_channel_asset_key(channel.slug, data.logo_key):
        raise HTTPException(status_code=422, detail="logo_key does not match channel")
    channel.logo_key = data.logo_key
    await db.commit()
    await db.refresh(channel)
    return channel
