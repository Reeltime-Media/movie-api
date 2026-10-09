"""Admin-only media preview — bypasses purchase/subscription checks."""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_playback_token
from app.dependencies import AdminUser, DBSession
from app.models.content import Content
from app.models.series import Series
from app.services import r2_keys, storage
from app.services.transcode_client import get_hls_export, start_hls_export

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


async def _load_content(db, content_id: uuid.UUID) -> Content:
    content = await db.scalar(select(Content).where(Content.id == content_id))
    if not content:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    return content


@router.get("/playback/{content_id}/authorize")
async def admin_authorize_playback(
    content_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    """Mint a playback token for admin preview (draft or published)."""
    content = await _load_content(db, content_id)
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


def _download_filename(content: Content) -> str:
    base = (content.slug or str(content.id)).strip() or "video"
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in base).strip("-._")
    return f"{safe or 'video'}.mp4"


@router.get("/content/{content_id}/source-url")
async def admin_source_video_url(
    content_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    """Presigned URL for the original source.mp4 (admin preview / download)."""
    content = await _load_content(db, content_id)

    source_key = await _source_key_for_content(db, content)
    if not source_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No source video is configured for this title",
        )

    exists = await asyncio.get_event_loop().run_in_executor(None, storage.object_exists, source_key)
    if not exists:
        can_rebuild = bool(content.hls_master_key)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Original source video was not found in storage",
                "can_rebuild_from_hls": can_rebuild,
            },
        )

    filename = _download_filename(content)
    url = storage.generate_presigned_download_url(
        source_key,
        _SOURCE_URL_TTL,
        filename=filename,
    )
    return {
        "url": url,
        "source_key": source_key,
        "filename": filename,
        "expires_in": _SOURCE_URL_TTL,
    }


@router.post("/content/{content_id}/rebuild-source-from-hls")
async def admin_rebuild_source_from_hls(
    content_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    """Queue an HLS→MP4 remux that writes back to the canonical source.mp4 key."""
    content = await _load_content(db, content_id)
    if not content.hls_master_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No HLS stream is available to rebuild from",
        )

    source_key = await _source_key_for_content(db, content)
    if not source_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No source video path is configured for this title",
        )

    exists = await asyncio.get_event_loop().run_in_executor(None, storage.object_exists, source_key)
    if exists:
        return {
            "export_id": None,
            "status": "already_exists",
            "dest_source_key": source_key,
            "detail": "Source video already exists; download it directly",
        }

    result = await start_hls_export(
        hls_master_key=content.hls_master_key,
        dest_source_key=source_key,
    )
    return {
        "export_id": result.get("export_id"),
        "status": result.get("status", "queued"),
        "dest_source_key": source_key,
    }


@router.get("/content/{content_id}/rebuild-source-from-hls/{export_id}")
async def admin_rebuild_source_from_hls_status(
    content_id: uuid.UUID,
    export_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    """Poll HLS→MP4 remux progress (export jobs live on the transcoder)."""
    # Ensure the content still exists / caller is authorized as admin.
    await _load_content(db, content_id)
    return await get_hls_export(str(export_id))
