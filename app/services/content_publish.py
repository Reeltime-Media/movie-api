from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content_status import validate_content_status
from app.models.content import Content
from app.models.transcode_job import TranscodeJob


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


async def movie_is_publishable(db: AsyncSession, movie: Content) -> bool:
    """Same rules as ensure_movie_publishable, but returns False instead of raising."""
    try:
        await ensure_movie_publishable(db, movie)
        return True
    except HTTPException:
        return False


def apply_movie_publish_state(
    movie: Content,
    *,
    status: str | None = None,
    publish_at: datetime | None = None,
    publish_at_set: bool = False,
) -> None:
    """Normalize status / is_published / publish_at for movies.

    - published → live now; clear schedule
    - scheduled → require publish_at; stay unpublished (no readiness check here)
    - draft / review → unpublished; clear schedule
    """
    if movie.type != "single":
        return

    if status is not None:
        try:
            validate_content_status(status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        movie.status = status

    if publish_at_set:
        if publish_at is not None and publish_at.tzinfo is None:
            publish_at = publish_at.replace(tzinfo=UTC)
        movie.publish_at = publish_at

    if movie.status == "published":
        movie.is_published = True
        movie.publish_at = None
        return

    if movie.status == "scheduled":
        if movie.publish_at is None:
            raise HTTPException(
                status_code=422,
                detail="publish_at is required when status is scheduled.",
            )
        movie.is_published = False
        return

    # draft / review
    movie.is_published = False
    movie.publish_at = None


def promote_scheduled_movie_to_published(movie: Content) -> None:
    """Called by the sweeper after readiness is confirmed."""
    movie.status = "published"
    movie.is_published = True
    movie.publish_at = None


def ensure_podcast_publishable(podcast: Content) -> None:
    if podcast.type != "podcast":
        return
    if not podcast.poster_key:
        raise HTTPException(status_code=422, detail="A cover image is required before publishing.")
    if not podcast.audio_key:
        raise HTTPException(status_code=422, detail="An audio file is required before publishing.")
