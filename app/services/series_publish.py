from datetime import UTC, datetime

from fastapi import HTTPException

from app.core.content_status import validate_content_status
from app.models.series import Series


def ensure_series_publishable(series: Series) -> None:
    if not series.poster_key:
        raise HTTPException(status_code=422, detail="A poster is required before publishing.")


def series_is_publishable(series: Series) -> bool:
    try:
        ensure_series_publishable(series)
        return True
    except HTTPException:
        return False


def apply_series_publish_state(
    series: Series,
    *,
    status: str | None = None,
    publish_at: datetime | None = None,
    publish_at_set: bool = False,
) -> None:
    """Normalize status / is_published / publish_at for series.

    - published → live now; clear schedule
    - scheduled → require publish_at; stay unpublished (readiness checked by sweeper)
    - draft / review → unpublished; clear schedule
    """
    if status is not None:
        try:
            validate_content_status(status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        series.status = status

    if publish_at_set:
        if publish_at is not None and publish_at.tzinfo is None:
            publish_at = publish_at.replace(tzinfo=UTC)
        series.publish_at = publish_at

    if series.status == "published":
        series.is_published = True
        series.publish_at = None
        return

    if series.status == "scheduled":
        if series.publish_at is None:
            raise HTTPException(
                status_code=422,
                detail="publish_at is required when status is scheduled.",
            )
        series.is_published = False
        return

    # draft / review
    series.is_published = False
    series.publish_at = None


def promote_scheduled_series_to_published(series: Series) -> None:
    """Called by the sweeper after readiness is confirmed."""
    series.status = "published"
    series.is_published = True
    series.publish_at = None


def apply_legacy_is_published(series: Series, is_published: bool) -> None:
    """Support older admin clients that only PATCH is_published."""
    if is_published:
        apply_series_publish_state(series, status="published")
    else:
        apply_series_publish_state(series, status="draft")
