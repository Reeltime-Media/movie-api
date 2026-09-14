import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.dependencies import CurrentUser, DBSession
from app.models.content import Content
from app.models.favorite import Favorite
from app.models.series import Series
from app.schemas.favorite import FavoriteRead

router = APIRouter(prefix="/favorites", tags=["favorites"])


async def _assert_favoritable(db: DBSession, target_id: uuid.UUID) -> None:
    result = await db.execute(select(Content).where(Content.id == target_id))
    content = result.scalar_one_or_none()
    if content and content.type == "single" and content.is_published:
        return

    result = await db.execute(select(Series).where(Series.id == target_id))
    series = result.scalar_one_or_none()
    if series and series.is_published:
        return

    raise NotFoundError("Title not found")


@router.get("", response_model=list[FavoriteRead])
@router.get("/", response_model=list[FavoriteRead])
async def list_favorites(db: DBSession, current_user: CurrentUser):
    result = await db.execute(
        select(Favorite)
        .where(Favorite.user_id == current_user.id)
        .order_by(Favorite.created_at.desc())
    )
    return result.scalars().all()


@router.put("/{content_id}", response_model=FavoriteRead)
async def add_favorite(content_id: uuid.UUID, db: DBSession, current_user: CurrentUser):
    await _assert_favoritable(db, content_id)

    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
            Favorite.content_id == content_id,
        )
    )
    favorite = result.scalar_one_or_none()
    if not favorite:
        favorite = Favorite(user_id=current_user.id, content_id=content_id)
        db.add(favorite)
        await db.commit()
        await db.refresh(favorite)
    return favorite


@router.delete("/{content_id}", status_code=204)
async def remove_favorite(content_id: uuid.UUID, db: DBSession, current_user: CurrentUser):
    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
            Favorite.content_id == content_id,
        )
    )
    favorite = result.scalar_one_or_none()
    if not favorite:
        return
    await db.delete(favorite)
    await db.commit()
