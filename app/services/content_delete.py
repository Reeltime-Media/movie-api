import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.models.transcode_job import TranscodeJob


async def delete_transcode_jobs_for_content(
    db: AsyncSession, content_id: uuid.UUID
) -> None:
    await db.execute(
        delete(TranscodeJob).where(TranscodeJob.content_id == content_id)
    )


async def delete_transcode_jobs_for_series(
    db: AsyncSession, series_id: uuid.UUID
) -> None:
    await db.execute(
        delete(TranscodeJob).where(
            TranscodeJob.content_id.in_(
                select(Content.id).where(Content.series_id == series_id)
            )
        )
    )
