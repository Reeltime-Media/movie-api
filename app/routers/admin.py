import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.transcode_job import TranscodeJob

router = APIRouter(prefix="/admin", tags=["admin"])


class TranscodeJobRead(BaseModel):
    id: uuid.UUID
    content_id: uuid.UUID
    source_key: str
    status: str
    attempts: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/transcode-jobs", response_model=list[TranscodeJobRead])
async def list_transcode_jobs(db: DBSession, _: AdminUser):
    result = await db.execute(
        select(TranscodeJob).order_by(TranscodeJob.created_at.desc())
    )
    return result.scalars().all()


@router.post("/transcode-jobs/{job_id}/retry", response_model=TranscodeJobRead)
async def retry_transcode_job(job_id: uuid.UUID, db: DBSession, _: AdminUser):
    result = await db.execute(select(TranscodeJob).where(TranscodeJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Transcode job not found")
    job.status = "queued"
    job.error = None
    await db.commit()
    await db.refresh(job)
    return job
