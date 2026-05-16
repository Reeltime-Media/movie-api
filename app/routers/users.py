import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.dependencies import AdminUser, CurrentUser, DBSession
from app.models.user import User
from app.schemas.user import UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def get_me(current_user: CurrentUser):
    return current_user


@router.patch("/me", response_model=UserRead)
async def update_me(data: UserUpdate, current_user: CurrentUser, db: DBSession):
    if data.full_name is not None:
        current_user.full_name = data.full_name
    if data.password is not None:
        current_user.password_hash = hash_password(data.password)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get("/", response_model=list[UserRead])
async def list_users(_: AdminUser, db: DBSession):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, _: AdminUser, db: DBSession):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    return user
