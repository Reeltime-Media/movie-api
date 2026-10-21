import asyncio
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    generate_reset_token,
    hash_password_async,
    hash_reset_token,
    verify_password_async,
)
from app.models.password_reset_token import PasswordResetToken
from app.models.telegram_auth_nonce import TelegramAuthNonce
from app.models.user import User
from app.schemas.user import TelegramAuthRequest, UserCreate
from app.services.email import send_password_reset_email
from app.services.guest import claim_guest_purchases
from app.services.session import create_session, revoke_all_user_sessions

settings = get_settings()

TELEGRAM_SYNTHETIC_EMAIL_DOMAIN = "users.reeltime.fun"


async def register_user(db: AsyncSession, data: UserCreate, guest_id: str | None = None) -> User:
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    if result.scalar_one_or_none():
        raise ConflictError("Unable to create account with this email")

    user = User(
        email=data.email.lower(),
        password_hash=await hash_password_async(data.password),
        full_name=data.full_name,
    )
    db.add(user)
    await db.flush()
    await claim_guest_purchases(db, user.id, guest_id)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
    user_agent: str | None = None,
    guest_id: str | None = None,
) -> tuple[User, str]:
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()

    if (
        not user
        or not user.password_hash
        or not await verify_password_async(password, user.password_hash)
    ):
        raise UnauthorizedError("Invalid email or password")

    if not user.is_active:
        raise UnauthorizedError("Account is disabled")

    await claim_guest_purchases(db, user.id, guest_id)
    session = await create_session(db, user.id, user_agent)
    await db.commit()
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
    db: AsyncSession,
    id_token: str,
    user_agent: str | None = None,
    guest_id: str | None = None,
) -> tuple[User, str]:
    claims = await asyncio.to_thread(_verify_google_id_token, id_token)

    google_sub = claims.get("sub")
    email = claims.get("email")
    if not google_sub or not email:
        raise UnauthorizedError("Google account is missing required profile data")
    if claims.get("email_verified") is not True:
        raise UnauthorizedError("Google email is not verified")

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
            # is_active must be set here: the column default only applies at
            # INSERT, so it would still be None at the check below and every
            # first-time Google user was rejected as "Account is disabled".
            user = User(
                email=email,
                google_id=google_sub,
                full_name=name,
                avatar_url=picture,
                password_hash=None,
                is_active=True,
            )
            db.add(user)

    if not user.is_active:
        raise UnauthorizedError("Account is disabled")

    if picture:
        user.avatar_url = picture
    if name and not user.full_name:
        user.full_name = name

    await db.flush()
    await claim_guest_purchases(db, user.id, guest_id)
    session = await create_session(db, user.id, user_agent)
    await db.commit()
    await db.refresh(user)
    token = create_access_token(user.id, user.role, session.id)
    return user, token


def _telegram_configured() -> bool:
    return bool(settings.telegram_bot_token.strip() and settings.telegram_bot_username.strip())


def verify_telegram_login_hash(payload: dict[str, str], bot_token: str) -> bool:
    """Validate Telegram Login Widget `hash` per Telegram docs."""
    received = payload.get("hash", "")
    if not received:
        return False
    check_rows = [f"{key}={value}" for key, value in sorted(payload.items()) if key != "hash"]
    data_check_string = "\n".join(check_rows)
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, received)


def telegram_synthetic_email(telegram_id: str) -> str:
    return f"telegram_{telegram_id}@{TELEGRAM_SYNTHETIC_EMAIL_DOMAIN}"


async def start_telegram_auth(db: AsyncSession) -> tuple[str, str, int]:
    """Create a nonce and return (nonce, bridge_url, expires_in_seconds)."""
    if not _telegram_configured():
        raise UnauthorizedError("Telegram sign-in is not configured")

    raw_nonce = secrets.token_urlsafe(24)
    nonce_hash = hash_reset_token(raw_nonce)
    expires_in = settings.telegram_auth_nonce_expire_minutes * 60
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.telegram_auth_nonce_expire_minutes)
    db.add(TelegramAuthNonce(nonce_hash=nonce_hash, expires_at=expires_at))
    await db.commit()

    base = settings.telegram_auth_page_url.strip().rstrip("/")
    query = urlencode(
        {
            "nonce": raw_nonce,
            "bot": settings.telegram_bot_username.strip().lstrip("@"),
        }
    )
    return raw_nonce, f"{base}?{query}", expires_in


async def _consume_telegram_nonce(db: AsyncSession, raw_nonce: str) -> None:
    nonce_hash = hash_reset_token(raw_nonce)
    result = await db.execute(
        select(TelegramAuthNonce)
        .where(TelegramAuthNonce.nonce_hash == nonce_hash)
        .with_for_update()
    )
    row = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if not row or row.status != "pending" or row.expires_at < now:
        raise UnauthorizedError("Telegram sign-in session expired. Try again.")
    row.status = "used"


async def authenticate_telegram(
    db: AsyncSession,
    data: TelegramAuthRequest,
    user_agent: str | None = None,
    guest_id: str | None = None,
) -> tuple[User, str]:
    if not _telegram_configured():
        raise UnauthorizedError("Telegram sign-in is not configured")

    now = datetime.now(UTC)
    if abs(int(now.timestamp()) - int(data.auth_date)) > settings.telegram_auth_max_age_seconds:
        raise UnauthorizedError("Telegram sign-in expired. Try again.")

    payload: dict[str, str] = {
        "id": str(data.id),
        "auth_date": str(data.auth_date),
        "hash": data.hash,
    }
    if data.first_name:
        payload["first_name"] = data.first_name
    if data.last_name:
        payload["last_name"] = data.last_name
    if data.username:
        payload["username"] = data.username
    if data.photo_url:
        payload["photo_url"] = data.photo_url

    if not verify_telegram_login_hash(payload, settings.telegram_bot_token.strip()):
        raise UnauthorizedError("Invalid Telegram sign-in")

    await _consume_telegram_nonce(db, data.nonce)

    telegram_id = str(data.id)
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    display_name = " ".join(
        part for part in (data.first_name, data.last_name) if part and part.strip()
    ).strip() or (data.username.strip() if data.username else None)

    if not user:
        email = telegram_synthetic_email(telegram_id)
        user = User(
            email=email,
            telegram_id=telegram_id,
            full_name=display_name,
            avatar_url=data.photo_url,
            password_hash=None,
            is_active=True,
        )
        db.add(user)
    else:
        if display_name and not user.full_name:
            user.full_name = display_name
        if data.photo_url:
            user.avatar_url = data.photo_url

    if not user.is_active:
        raise UnauthorizedError("Account is disabled")

    await db.flush()
    await claim_guest_purchases(db, user.id, guest_id)
    session = await create_session(db, user.id, user_agent)
    await db.commit()
    await db.refresh(user)
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
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.password_reset_token_expire_minutes)
    db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    await db.commit()

    reset_link = f"{_reset_base_url()}/reset-password?token={raw_token}"
    await send_password_reset_email(to=user.email, reset_link=reset_link)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    token_hash = hash_reset_token(token)
    result = await db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    )
    reset_token = result.scalar_one_or_none()

    now = datetime.now(UTC)
    if not reset_token or reset_token.used_at is not None or reset_token.expires_at < now:
        raise UnauthorizedError("This reset link is invalid or has expired")

    user = await db.get(User, reset_token.user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("This reset link is invalid or has expired")

    user.password_hash = await hash_password_async(new_password)
    reset_token.used_at = now
    # Stolen access tokens must stop working as soon as the password changes.
    await revoke_all_user_sessions(db, user.id)
    await db.commit()
