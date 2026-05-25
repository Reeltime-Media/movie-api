from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate

settings = get_settings()


async def register_user(db: AsyncSession, data: UserCreate) -> User:
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    if result.scalar_one_or_none():
        raise ConflictError("Unable to create account with this email")

    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        full_name=data.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(
    db: AsyncSession, email: str, password: str
) -> tuple[User, str]:
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")

    if not user.is_active:
        raise UnauthorizedError("Account is disabled")

    token = create_access_token(user.id, user.role)
    return user, token


def _verify_google_id_token(token: str) -> dict:
    if not settings.google_client_id:
        raise UnauthorizedError("Google sign-in is not configured")
    try:
        return google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except ValueError as exc:
        raise UnauthorizedError("Invalid Google token") from exc


async def authenticate_google(db: AsyncSession, id_token: str) -> tuple[User, str]:
    claims = _verify_google_id_token(id_token)

    google_sub = claims.get("sub")
    email = claims.get("email")
    if not google_sub or not email:
        raise UnauthorizedError("Google account is missing required profile data")

    email = email.lower()
    name = claims.get("name") or claims.get("given_name")
    picture = claims.get("picture")

    result = await db.execute(select(User).where(User.google_id == google_sub))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            if user.google_id and user.google_id != google_sub:
                raise ConflictError("Email is linked to a different Google account")
            user.google_id = google_sub
            if picture:
                user.avatar_url = picture
            if name and not user.full_name:
                user.full_name = name
        else:
            user = User(
                email=email,
                google_id=google_sub,
                full_name=name,
                avatar_url=picture,
                password_hash=None,
            )
            db.add(user)

    if not user.is_active:
        raise UnauthorizedError("Account is disabled")

    if picture:
        user.avatar_url = picture
    if name and not user.full_name:
        user.full_name = name

    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.role)
    return user, token
