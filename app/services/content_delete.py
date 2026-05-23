import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.transcode_job import TranscodeJob
from app.models.watch_progress import WatchProgress


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


async def delete_content_dependencies(
    db: AsyncSession, content_id: uuid.UUID
) -> None:
    """Remove rows that reference content before deleting the content record."""
    await db.execute(delete(Purchase).where(Purchase.content_id == content_id))
    await db.execute(
        delete(WatchProgress).where(WatchProgress.content_id == content_id)
    )
    await db.execute(
        update(PaymentIntent)
        .where(PaymentIntent.content_id == content_id)
        .values(content_id=None)
    )
    await delete_transcode_jobs_for_content(db, content_id)


async def delete_content_dependencies_for_series(
    db: AsyncSession, series_id: uuid.UUID
) -> None:
    result = await db.execute(
        select(Content.id).where(Content.series_id == series_id)
    )
    for (content_id,) in result.all():
        await delete_content_dependencies(db, content_id)
