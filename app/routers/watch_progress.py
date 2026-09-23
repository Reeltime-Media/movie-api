import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.dependencies import CurrentUser, DBSession
from app.models.content import Content
from app.models.series import Series
from app.models.watch_progress import WatchProgress
from app.schemas.watch_progress import (
    WatchProgressContentRead,
    WatchProgressRead,
    WatchProgressSeriesRead,
    WatchProgressUpdate,
)
from app.services.content_access import assert_can_track_watch_progress

router = APIRouter(prefix="/watch-progress", tags=["watch-progress"])


@router.get("", response_model=list[WatchProgressRead])
@router.get("/", response_model=list[WatchProgressRead])
async def list_watch_progress(db: DBSession, current_user: CurrentUser):
    result = await db.execute(
        select(WatchProgress, Content, Series)
        .join(Content, Content.id == WatchProgress.content_id)
        .outerjoin(Series, Series.id == Content.series_id)
        .where(WatchProgress.user_id == current_user.id)
        .order_by(WatchProgress.last_watched_at.desc(), WatchProgress.content_id)
    )
    return [_history_row(progress, content, series) for progress, content, series in result.all()]


def _history_row(progress: WatchProgress, content: Content, series: Series | None) -> WatchProgressRead:
    """Include public navigation metadata, never stream keys or entitlement grants."""
    row = WatchProgressRead.model_validate(progress)
    if not content.is_published:
        return row
    if content.type == "episode" and (series is None or not series.is_published):
        return row
    details = WatchProgressContentRead.model_validate(content)
    if content.type == "episode":
        details.series = WatchProgressSeriesRead.model_validate(series)
    row.content = details
    return row


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
