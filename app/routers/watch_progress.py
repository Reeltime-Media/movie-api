import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.dependencies import CurrentUser, DBSession
from app.models.watch_progress import WatchProgress
from app.schemas.watch_progress import WatchProgressRead, WatchProgressUpdate
from app.services.content_access import assert_can_track_watch_progress

router = APIRouter(prefix="/watch-progress", tags=["watch-progress"])


@router.get("/", response_model=list[WatchProgressRead])
async def list_watch_progress(db: DBSession, current_user: CurrentUser):
    result = await db.execute(
        select(WatchProgress).where(WatchProgress.user_id == current_user.id)
    )
    return result.scalars().all()


@router.get("/{content_id}", response_model=WatchProgressRead)
async def get_watch_progress(
    content_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(WatchProgress).where(
            WatchProgress.user_id == current_user.id,
            WatchProgress.content_id == content_id,
        )
    )
    progress = result.scalar_one_or_none()
    if not progress:
        raise HTTPException(status_code=404, detail="Watch progress not found")
    return progress


@router.put("/{content_id}", response_model=WatchProgressRead)
async def upsert_watch_progress(
    content_id: uuid.UUID,
    data: WatchProgressUpdate,
    db: DBSession,
    current_user: CurrentUser,
):
    await assert_can_track_watch_progress(db, current_user, content_id)

    result = await db.execute(
        select(WatchProgress).where(
            WatchProgress.user_id == current_user.id,
            WatchProgress.content_id == content_id,
        )
    )
    progress = result.scalar_one_or_none()

    if progress:
        progress.position_seconds = data.position_seconds
        progress.completed = data.completed
        progress.last_watched_at = datetime.now(timezone.utc)
    else:
        progress = WatchProgress(
            user_id=current_user.id,
            content_id=content_id,
            position_seconds=data.position_seconds,
            completed=data.completed,
            last_watched_at=datetime.now(timezone.utc),
        )
        db.add(progress)

    await db.commit()
    await db.refresh(progress)
    return progress
