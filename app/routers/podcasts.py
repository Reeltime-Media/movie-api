"""Public podcast catalog + audio authorize."""

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from app.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.guest import get_guest_id
from app.dependencies import DBSession, OptionalUser
from app.models.content import Content
from app.schemas.content import ContentListItemRead, ContentRead
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services import storage
from app.services.content_access import can_access_content
from app.services.pagination import paginate_query

router = APIRouter(prefix="/podcasts", tags=["podcasts"])
settings = get_settings()


@router.get("/", response_model=PaginatedResponse[ContentListItemRead])
@router.get("", response_model=PaginatedResponse[ContentListItemRead])
async def list_podcasts(
    db: DBSession,
    pagination: PaginationDep,
    search: str | None = Query(default=None),
):
    stmt = (
        select(Content)
        .where(Content.type == "podcast", Content.is_published.is_(True))
        .order_by(Content.created_at.desc())
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.where(Content.title.ilike(term) | Content.title_km.ilike(term))
    items, total = await paginate_query(
        db, stmt, page=pagination.page, page_size=pagination.page_size
    )
    return build_paginated_response(
        [ContentListItemRead.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{content_id}/audio")
async def authorize_podcast_audio(
    content_id: uuid.UUID,
    db: DBSession,
    request: Request,
    user: OptionalUser,
):
    """Return a playable audio URL when the viewer is entitled (free or Plan)."""
    result = await db.execute(
        select(Content).where(Content.id == content_id, Content.type == "podcast")
    )
    podcast = result.scalar_one_or_none()
    if not podcast or (not podcast.is_published and not (user and user.role == "admin")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Podcast not found")

    guest_id = None if user else get_guest_id(request)
    if not await can_access_content(db, user, guest_id, podcast):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Subscribe to unlock this podcast",
        )
    if not podcast.audio_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This podcast is not ready to play yet",
        )

    expires_in = settings.playback_token_expiry_seconds
    return {
        "audio_url": storage.generate_playback_segment_url(podcast.audio_key, expires_in),
        "expires_in": expires_in,
        "content_id": str(podcast.id),
        "title": podcast.title,
    }


@router.get("/{slug}", response_model=ContentRead)
async def get_podcast(
    slug: str,
    db: DBSession,
    request: Request,
    user: OptionalUser,
):
    result = await db.execute(
        select(Content).where(Content.slug == slug, Content.type == "podcast")
    )
    podcast = result.scalar_one_or_none()
    if not podcast or not podcast.is_published:
        if not (user and user.role == "admin" and podcast):
            raise NotFoundError("Podcast not found")

    data = ContentRead.model_validate(podcast)
    guest_id = None if user else get_guest_id(request)
    if not await can_access_content(db, user, guest_id, podcast):
        data.audio_key = None
    return data
