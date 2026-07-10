import uuid

from fastapi import APIRouter
from sqlalchemy import delete, select

from app.core.exceptions import NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.content import Content
from app.models.series import Series
from app.schemas.content import SeasonRead
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.schemas.series import SeriesRead
from app.services.content_delete import delete_series_and_dependencies
from app.services.pagination import paginate_query

router = APIRouter()


@router.get("/series", response_model=PaginatedResponse[SeriesRead])
async def list_admin_series(
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
):
    stmt = select(Series).order_by(Series.created_at.desc())
    items, total = await paginate_query(
        db, stmt, page=pagination.page, page_size=pagination.page_size
    )
    return build_paginated_response(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/series/{series_id}", response_model=SeriesRead)
async def get_admin_series(series_id: uuid.UUID, db: DBSession, _: AdminUser):
    result = await db.execute(select(Series).where(Series.id == series_id))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")
    return series


@router.get("/series/{series_slug}/episodes", response_model=list[SeasonRead])
async def list_admin_series_episodes(series_slug: str, db: DBSession, _: AdminUser):
    """All episodes for a series (draft + published), grouped by season."""
    series_result = await db.execute(select(Series).where(Series.slug == series_slug))
    series = series_result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")

    eps_result = await db.execute(
        select(Content)
        .where(Content.series_id == series.id)
        .order_by(Content.season_number, Content.episode_number)
    )
    episodes = eps_result.scalars().all()

    seasons: dict[int, list[Content]] = {}
    for ep in episodes:
        sn = ep.season_number or 1
        seasons.setdefault(sn, []).append(ep)

    return [
        SeasonRead(season_number=sn, episodes=eps)
        for sn, eps in sorted(seasons.items())
    ]


@router.delete("/series/{series_id}", status_code=204)
async def delete_admin_series(series_id: uuid.UUID, db: DBSession, _: AdminUser):
    """Delete a series, all episodes, and related rows."""
    result = await db.execute(select(Series).where(Series.id == series_id))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")
    await delete_series_and_dependencies(db, series.id)
    await db.delete(series)
    await db.commit()
