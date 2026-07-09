"""Admin-only media preview — bypasses purchase/subscription checks."""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_playback_token
from app.dependencies import AdminUser, DBSession
from app.models.content import Content
from app.models.series import Series
from app.services import r2_keys, storage

router = APIRouter()
settings = get_settings()

_SOURCE_URL_TTL = 3600


async def _source_key_for_content(db, content: Content) -> str | None:
    if content.type == "single":
        return r2_keys.movie_source_key(content.slug)
    if content.type == "episode":
        if not content.series_id:
            return None
        series = await db.get(Series, content.series_id)
        if not series:
            return None
        return r2_keys.episode_source_key(series.slug, content.slug)
    return None


@router.get("/playback/{content_id}/authorize")
async def admin_authorize_playback(
    content_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    """Mint a playback token for admin preview (draft or published)."""
    content = await db.scalar(select(Content).where(Content.id == content_id))
    if not content:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    if not content.hls_master_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This title is not ready to stream yet",
        )
    token = create_playback_token(content_id, settings.playback_token_expiry_seconds)
    return {
        "master_url": f"/playback/{content_id}/master.m3u8?t={token}",
        "expires_in": settings.playback_token_expiry_seconds,
    }


@router.get("/content/{content_id}/source-url")
async def admin_source_video_url(
    content_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    """Presigned URL for the original source.mp4 (admin preview)."""
    content = await db.scalar(select(Content).where(Content.id == content_id))
    if not content:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")

    source_key = await _source_key_for_content(db, content)
    if not source_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No source video is configured for this title",
        )

    exists = await asyncio.get_event_loop().run_in_executor(
        None, storage.object_exists, source_key
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Original source video was not found in storage",
        )

    url = storage.generate_presigned_download_url(source_key, _SOURCE_URL_TTL)
    return {
        "url": url,
        "source_key": source_key,
        "expires_in": _SOURCE_URL_TTL,
    }
