from fastapi import APIRouter
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, CurrentUser, DBSession
from app.models.series import Series
from app.schemas.series import SeriesCreate, SeriesRead, SeriesUpdate

router = APIRouter(prefix="/series", tags=["series"])


@router.get("/", response_model=list[SeriesRead])
async def list_series(db: DBSession, _: CurrentUser):
    result = await db.execute(select(Series).where(Series.is_published.is_(True)))
    return result.scalars().all()


@router.get("/{slug}", response_model=SeriesRead)
async def get_series(slug: str, db: DBSession, _: CurrentUser):
    result = await db.execute(select(Series).where(Series.slug == slug))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")
    return series


@router.post("/", response_model=SeriesRead, status_code=201)
async def create_series(data: SeriesCreate, db: DBSession, _: AdminUser):
    existing = await db.execute(select(Series).where(Series.slug == data.slug))
    if existing.scalar_one_or_none():
        raise ConflictError("Slug already exists")
    series = Series(**data.model_dump())
    db.add(series)
    await db.commit()
    await db.refresh(series)
    return series


@router.patch("/{slug}", response_model=SeriesRead)
async def update_series(slug: str, data: SeriesUpdate, db: DBSession, _: AdminUser):
    result = await db.execute(select(Series).where(Series.slug == slug))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(series, field, value)
    await db.commit()
    await db.refresh(series)
    return series


@router.delete("/{slug}", status_code=204)
async def delete_series(slug: str, db: DBSession, _: AdminUser):
    result = await db.execute(select(Series).where(Series.slug == slug))
    series = result.scalar_one_or_none()
    if not series:
        raise NotFoundError("Series not found")
    await db.delete(series)
    await db.commit()
