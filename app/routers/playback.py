"""Token-gated HLS playback endpoints.

Flow:
  1. GET /playback/{content_id}/authorize  (requires login + entitlement)
       -> mints a short-lived playback token, returns the master playlist URL.
  2. GET /playback/{content_id}/master.m3u8?t=<token>
       -> rewritten master; rendition refs point at the variant endpoint.
  3. GET /playback/{content_id}/v/{name}?t=<token>
       -> rewritten rendition playlist; segment refs point at the segment endpoint.
  4. GET /playback/{content_id}/s/{name}?t=<token>
       -> proxies the .ts segment from R2 (same-origin for the browser).

Because the token rides in the URL, this works for both hls.js (MSE) and
Safari's native HLS, with no custom request headers anywhere in the chain.
"""

import posixpath
import re
import uuid

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_playback_token, verify_playback_token
from app.dependencies import CurrentUser, DBSession
from app.models.content import Content
from app.services import playback
from app.services.content_access import (
    get_published_content_or_404,
    user_can_access_content,
)

router = APIRouter(prefix="/playback", tags=["playback"])
settings = get_settings()

_M3U8_MEDIA_TYPE = "application/vnd.apple.mpegurl"
# Rendition playlist filename as written by the transcoder, e.g. "720p.m3u8".
_VARIANT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.m3u8$")
# HLS transport stream segment, e.g. "720p_00001.ts".
_SEGMENT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.ts$")
# Playlists carry token URLs — never let a shared cache store them.
_NO_STORE = {"Cache-Control": "no-store"}
# Segments are immutable once transcoded; token still gates access.
_SEGMENT_CACHE = {"Cache-Control": "private, max-age=3600"}


async def _content_or_404(db, content_id: uuid.UUID) -> Content:
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Content not found"
        )
    if not content.hls_master_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This title is not ready to stream yet",
        )
    return content


@router.get("/{content_id}/authorize")
async def authorize_playback(content_id: uuid.UUID, db: DBSession, user: CurrentUser):
    """Verify entitlement and hand back a tokenized master playlist URL."""
    content = await get_published_content_or_404(db, content_id, user=user)
    if not await user_can_access_content(db, user, content):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this title",
        )
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


@router.get("/{content_id}/master.m3u8")
async def master_playlist(
    content_id: uuid.UUID, db: DBSession, t: str = Query(...)
) -> Response:
    verify_playback_token(t, content_id)
    content = await _content_or_404(db, content_id)
    body = await playback.build_master_playlist(content.hls_master_key, content_id, t)
    return Response(content=body, media_type=_M3U8_MEDIA_TYPE, headers=_NO_STORE)


@router.get("/{content_id}/v/{name}")
async def variant_playlist(
    content_id: uuid.UUID, name: str, db: DBSession, t: str = Query(...)
) -> Response:
    if not _VARIANT_NAME_RE.match(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid rendition"
        )
    verify_playback_token(t, content_id)
    content = await _content_or_404(db, content_id)
    body = await playback.build_variant_playlist(content.hls_master_key, name, t)
    return Response(content=body, media_type=_M3U8_MEDIA_TYPE, headers=_NO_STORE)


@router.get("/{content_id}/s/{name}")
async def segment(
    content_id: uuid.UUID, name: str, db: DBSession, t: str = Query(...)
) -> Response:
    if not _SEGMENT_NAME_RE.match(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid segment"
        )
    if posixpath.basename(name) != name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid segment"
        )
    verify_playback_token(t, content_id)
    content = await _content_or_404(db, content_id)
    try:
        body, media_type = await playback.get_segment_bytes(
            content.hls_master_key, name
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found"
            ) from exc
        raise
    return Response(content=body, media_type=media_type, headers=_SEGMENT_CACHE)
