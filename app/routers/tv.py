"""Token-gated live TV channel listing + playback.

Flow:
  1. GET /tv/channels                          -> public channel list.
  2. GET /tv/channels/{channel_id}/authorize    (requires entitlement — an
     active subscription, or the channel is marked free)
       -> mints a short-lived playback token, returns the entry playlist URL.
  3. GET /tv/{channel_id}/live.m3u8?t=<token>
       -> proxies the channel's live playlist once, rewriting every URI to an
          absolute URL on the origin server. The player then talks to the
          origin server (or its CDN) directly for everything else (nested
          playlists, segments) — this API never sits in the hot path of live
          traffic.
"""

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_channel_playback_token, verify_channel_playback_token
from app.dependencies import DBSession, OptionalUser
from app.models.tv_channel import TVChannel
from app.schemas.channel import TVChannelAuthorizeRead, TVChannelPublicRead
from app.services import live_playback
from app.services.content_access import can_access_channel

router = APIRouter(prefix="/tv", tags=["tv"])
settings = get_settings()

_M3U8_MEDIA_TYPE = "application/vnd.apple.mpegurl"
_NO_STORE = {"Cache-Control": "no-store"}


def _public_status(status_value: str) -> str:
    return "live" if status_value == "live" else "offline"


async def _published_channel_or_404(db, channel_id: uuid.UUID) -> TVChannel:
    result = await db.execute(
        select(TVChannel).where(
            TVChannel.id == channel_id, TVChannel.is_published.is_(True)
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return channel


@router.get("/channels", response_model=list[TVChannelPublicRead])
async def list_channels(db: DBSession):
    result = await db.execute(
        select(TVChannel)
        .where(TVChannel.is_published.is_(True))
        .order_by(TVChannel.sort_order, TVChannel.name)
    )
    channels = result.scalars().all()
    return [
        TVChannelPublicRead(
            id=channel.id,
            slug=channel.slug,
            name=channel.name,
            description=channel.description,
            logo_key=channel.logo_key,
            status=_public_status(channel.status),
            is_free=channel.is_free,
        )
        for channel in channels
    ]


@router.get("/channels/{channel_id}/authorize", response_model=TVChannelAuthorizeRead)
async def authorize_channel_playback(
    channel_id: uuid.UUID, db: DBSession, user: OptionalUser
):
    channel = await _published_channel_or_404(db, channel_id)
    if not await can_access_channel(db, user, channel):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this channel",
        )
    if channel.status != "live" or not channel.hls_playback_url:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This channel is not live right now",
        )
    token = create_channel_playback_token(
        channel_id, settings.tv_playback_token_expiry_seconds
    )
    return {
        "master_url": f"/tv/{channel_id}/live.m3u8?t={token}",
        "expires_in": settings.tv_playback_token_expiry_seconds,
    }


@router.get("/{channel_id}/live.m3u8")
async def channel_live_playlist(
    channel_id: uuid.UUID, db: DBSession, t: str = Query(...)
) -> Response:
    verify_channel_playback_token(t, channel_id)
    channel = await _published_channel_or_404(db, channel_id)
    if channel.status != "live" or not channel.hls_playback_url:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This channel is not live right now",
        )
    body = await live_playback.build_channel_playlist(channel.hls_playback_url)
    return Response(content=body, media_type=_M3U8_MEDIA_TYPE, headers=_NO_STORE)
