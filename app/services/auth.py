from datetime import datetime, timedelta, timezone

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    generate_reset_token,
    hash_password,
    hash_reset_token,
    verify_password,
)
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.schemas.user import UserCreate
from app.services.email import send_password_reset_email
from app.services.session import create_session

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
    db: AsyncSession, email: str, password: str, user_agent: str | None = None
) -> tuple[User, str]:
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")

    if not user.is_active:
        raise UnauthorizedError("Account is disabled")

    session = await create_session(db, user.id, user_agent)
    token = create_access_token(user.id, user.role, session.id)
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


async def authenticate_google(
    db: AsyncSession, id_token: str, user_agent: str | None = None
) -> tuple[User, str]:
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

    session = await create_session(db, user.id, user_agent)
    token = create_access_token(user.id, user.role, session.id)
    return user, token


def _reset_base_url() -> str:
    if settings.app_public_url:
        return settings.app_public_url.strip().rstrip("/")
    return settings.cors_origin_list[0].rstrip("/")


async def request_password_reset(db: AsyncSession, email: str) -> None:
    """Always succeeds from the caller's perspective — whether or not the
    email matches an account is never revealed, to avoid user enumeration."""
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return

    # Drop any outstanding tokens so only the newest link works.
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))

    raw_token, token_hash = generate_reset_token()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.password_reset_token_expire_minutes
    )
    db.add(
        PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
    )
    await db.commit()

    reset_link = f"{_reset_base_url()}/reset-password?token={raw_token}"
    await send_password_reset_email(to=user.email, reset_link=reset_link)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    token_hash = hash_reset_token(token)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    reset_token = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if (
        not reset_token
        or reset_token.used_at is not None
        or reset_token.expires_at < now
    ):
        raise UnauthorizedError("This reset link is invalid or has expired")

    user = await db.get(User, reset_token.user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("This reset link is invalid or has expired")

    user.password_hash = hash_password(new_password)
    reset_token.used_at = now
    await db.commit()
