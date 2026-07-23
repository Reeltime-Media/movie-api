import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.transcode_job import TranscodeJob
from app.schemas.admin import TranscodeJobRead
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services.admin.helpers import (
    transcode_job_row_to_read,
    transcode_jobs_select,
)
from app.services.pagination import paginate_query

router = APIRouter()


@router.get("/transcode-jobs/counts")
async def admin_transcode_job_counts(db: DBSession, _: AdminUser):
    """Single query for admin filter badges — avoids 5 paginated list round-trips."""
    result = await db.execute(
        select(TranscodeJob.status, func.count())
        .group_by(TranscodeJob.status)
    )
    by_status = {status: count for status, count in result.all()}
    queued = int(by_status.get("queued", 0))
    running = int(by_status.get("running", 0))
    success = int(by_status.get("success", 0))
    failed = int(by_status.get("failed", 0))
    return {
        "all": queued + running + success + failed,
        "queued": queued,
        "running": running,
        "success": success,
        "failed": failed,
    }


@router.get("/transcode-jobs", response_model=PaginatedResponse[TranscodeJobRead])
async def list_transcode_jobs(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
    status: str | None = Query(
        default=None,
        description="Filter by job status: queued, running, success, failed",
    ),
):
    stmt = transcode_jobs_select().order_by(TranscodeJob.created_at.desc())
    if status:
        stmt = stmt.where(TranscodeJob.status == status)
    rows, total = await paginate_query(
        db,
        stmt,
        page=pagination.page,
        page_size=pagination.page_size,
        scalar=False,
    )
    return build_paginated_response(
        [transcode_job_row_to_read(row) for row in rows],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/transcode-jobs/progress")
async def admin_transcode_jobs_progress(_: AdminUser):
    from app.services.transcode_client import fetch_jobs_progress

    return await fetch_jobs_progress()


@router.post("/transcode-jobs/{job_id}/cancel")
async def admin_cancel_transcode_job(job_id: uuid.UUID, _: AdminUser):
    from app.services.transcode_client import cancel_job

    return await cancel_job(str(job_id))


@router.post("/transcode-jobs/{job_id}/retry", response_model=TranscodeJobRead)
async def retry_transcode_job(job_id: uuid.UUID, db: DBSession, _: AdminUser):
    result = await db.execute(select(TranscodeJob).where(TranscodeJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Transcode job not found")
    job.status = "queued"
    job.error = None
    await db.commit()
    row = (
        await db.execute(transcode_jobs_select().where(TranscodeJob.id == job_id))
    ).one()
    return transcode_job_row_to_read(row)
