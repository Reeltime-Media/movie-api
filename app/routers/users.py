import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.dependencies import AdminUser, CurrentUser, DBSession
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.schemas.user import UserRead, UserStatusUpdate, UserUpdate, user_to_read
from app.services.pagination import paginate_query

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def get_me(current_user: CurrentUser):
    return user_to_read(current_user)


@router.patch("/me", response_model=UserRead)
async def update_me(data: UserUpdate, current_user: CurrentUser, db: DBSession):
    if data.full_name is not None:
        current_user.full_name = data.full_name
    if data.password is not None:
        current_user.password_hash = hash_password(data.password)
    await db.commit()
    await db.refresh(current_user)
    return user_to_read(current_user)


@router.get("", response_model=PaginatedResponse[UserRead])
@router.get("/", response_model=PaginatedResponse[UserRead])
async def list_users(
    _: AdminUser,
    db: DBSession,
    pagination: PaginationDep,
):
    stmt = select(User).order_by(User.created_at.desc())
    items, total = await paginate_query(
        db, stmt, page=pagination.page, page_size=pagination.page_size
    )
    return build_paginated_response(
        [user_to_read(u) for u in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, _: AdminUser, db: DBSession):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    return user_to_read(user)


@router.patch("/{user_id}", response_model=UserRead)
async def admin_update_user_status(
    user_id: uuid.UUID,
    data: UserStatusUpdate,
    admin: AdminUser,
    db: DBSession,
):
    if user_id == admin.id:
        raise ForbiddenError("You cannot change your own account status")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    user.is_active = data.is_active
    await db.commit()
    await db.refresh(user)
    return user_to_read(user)


@router.delete("/{user_id}", status_code=204)
async def admin_delete_user(user_id: uuid.UUID, admin: AdminUser, db: DBSession):
    if user_id == admin.id:
        raise ForbiddenError("You cannot delete your own account")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    await db.delete(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            "Cannot delete a user with payments, purchases, or subscriptions. "
            "Suspend the account instead."
        )
