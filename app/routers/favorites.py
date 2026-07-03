import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.dependencies import CurrentUser, DBSession
from app.models.content import Content
from app.models.favorite import Favorite
from app.schemas.favorite import FavoriteRead

router = APIRouter(prefix="/favorites", tags=["favorites"])


async def _assert_favoritable_movie(db: DBSession, content_id: uuid.UUID) -> Content:
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content or content.type != "single" or not content.is_published:
        raise NotFoundError("Movie not found")
    return content


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
    await _assert_favoritable_movie(db, content_id)

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
