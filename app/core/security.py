from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from jwt.exceptions import PyJWTError
from passlib.context import CryptContext

from app.config import get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: UUID, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except PyJWTError:
        raise UnauthorizedError("Could not validate credentials")


def create_playback_token(content_id: UUID, expires_in: int) -> str:
    """Short-lived token scoped to a single content id, minted only after an
    entitlement check. It gates the HLS playlist endpoints so the user's main
    access token never appears in playlist bodies or media URLs."""
    expire = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    payload = {"sub": str(content_id), "scope": "playback", "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def verify_playback_token(token: str, content_id: UUID) -> None:
    """Raise 401/403 unless `token` is a valid playback token for `content_id`."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except PyJWTError:
        raise UnauthorizedError("Invalid or expired playback token")
    if payload.get("scope") != "playback" or payload.get("sub") != str(content_id):
        raise ForbiddenError("Playback token does not grant access to this content")
