import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.dependencies.db import DBSession
from app.models.user import User
from app.services.session import require_active_session

bearer_scheme = HTTPBearer()
optional_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: DBSession,
) -> User:
    payload = decode_access_token(credentials.credentials)
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token payload")
    # Checking the session on every request (rather than trusting the JWT
    # alone) is what makes logout / the device limit take effect
    # immediately instead of waiting up to ACCESS_TOKEN_EXPIRE_MINUTES.
    await require_active_session(db, payload.get("sid"))
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_session_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: DBSession,
) -> uuid.UUID:
    payload = decode_access_token(credentials.credentials)
    return await require_active_session(db, payload.get("sid"))


CurrentSessionId = Annotated[uuid.UUID, Depends(get_current_session_id)]


async def get_current_user_optional(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(optional_bearer_scheme)
    ],
    db: DBSession,
) -> User | None:
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        await require_active_session(db, payload.get("sid"))
    except UnauthorizedError:
        return None
    user_id: str | None = payload.get("sub")
    if not user_id:
        return None
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return None
    return user


OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]


async def require_admin(current_user: CurrentUser) -> User:
    if current_user.role != "admin":
        raise ForbiddenError("Admin access required")
    return current_user


AdminUser = Annotated[User, Depends(require_admin)]
