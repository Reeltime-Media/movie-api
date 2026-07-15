import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.models.purchase import Purchase
from app.models.series import Series
from app.models.transcode_job import TranscodeJob
from app.models.watch_progress import WatchProgress
from app.schemas.admin import TranscodeJobRead


def transcode_jobs_select():
    return (
        select(
            TranscodeJob,
            Content.title.label("content_title"),
            Content.type.label("content_type"),
            Content.slug.label("content_slug"),
            Content.series_id.label("series_id"),
            Series.title.label("series_title"),
            Content.season_number.label("season_number"),
            Content.episode_number.label("episode_number"),
        )
        .outerjoin(Content, Content.id == TranscodeJob.content_id)
        .outerjoin(Series, Series.id == Content.series_id)
    )


def transcode_job_row_to_read(row) -> TranscodeJobRead:
    (
        job,
        content_title,
        content_type,
        content_slug,
        series_id,
        series_title,
        season_number,
        episode_number,
    ) = row
    return TranscodeJobRead(
        id=job.id,
        content_id=job.content_id,
        source_key=job.source_key,
        status=job.status,
        attempts=job.attempts,
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
        content_title=content_title,
        content_type=content_type,
        content_slug=content_slug,
        series_id=series_id,
        series_title=series_title,
        season_number=season_number,
        episode_number=episode_number,
    )


async def watch_counts_for_content(
    db: AsyncSession, content_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not content_ids:
        return {}
    result = await db.execute(
        select(
            WatchProgress.content_id,
            func.count(WatchProgress.user_id).label("watch_count"),
        )
        .where(WatchProgress.content_id.in_(content_ids))
        .group_by(WatchProgress.content_id)
    )
    return {row.content_id: int(row.watch_count) for row in result.all()}


async def purchase_counts_for_content(
    db: AsyncSession, content_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Purchases per content id. Ids with no purchases are absent — callers default to 0."""
    if not content_ids:
        return {}
    result = await db.execute(
        select(
            Purchase.content_id,
            func.count(Purchase.id).label("purchase_count"),
        )
        .where(Purchase.content_id.in_(content_ids))
        .group_by(Purchase.content_id)
    )
    return {row.content_id: int(row.purchase_count) for row in result.all()}
