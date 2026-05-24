from fastapi import HTTPException
from sqlalchemy import select

from app.models.content import Content
from app.models.transcode_job import TranscodeJob
from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_movie_publishable(db: AsyncSession, movie: Content) -> None:
    if movie.type != "single":
        return
    if not movie.poster_key:
        raise HTTPException(status_code=422, detail="A poster is required before publishing.")
    if movie.hls_master_key:
        return
    if movie.transcode_status in ("processing", "ready"):
        return
    job = await db.scalar(
        select(TranscodeJob.id).where(TranscodeJob.content_id == movie.id).limit(1)
    )
    if job:
        return
    raise HTTPException(status_code=422, detail="A movie video is required before publishing.")
