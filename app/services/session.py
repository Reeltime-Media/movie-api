import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.models.session import Session

settings = get_settings()

_OS_PATTERNS = (
    (re.compile(r"iPhone|iPad"), "iOS"),
    (re.compile(r"Android"), "Android"),
    (re.compile(r"Mac OS X"), "macOS"),
    (re.compile(r"Windows"), "Windows"),
    (re.compile(r"Linux"), "Linux"),
)
_BROWSER_PATTERNS = (
    (re.compile(r"Edg/"), "Edge"),
    (re.compile(r"OPR/|Opera"), "Opera"),
    (re.compile(r"Chrome/"), "Chrome"),
    (re.compile(r"CriOS/"), "Chrome"),
    (re.compile(r"FxiOS/"), "Firefox"),
    (re.compile(r"Firefox/"), "Firefox"),
    (re.compile(r"Safari/"), "Safari"),
)


def device_label_from_user_agent(user_agent: str | None) -> str:
    """Coarse, best-effort '<Browser> on <OS>' label for a device list UI.
    Not meant to fingerprint — just enough for a user to recognize which
    device is which when deciding what to revoke."""
    if not user_agent:
        return "Unknown device"

    browser = next((name for pattern, name in _BROWSER_PATTERNS if pattern.search(user_agent)), None)
    os_name = next((name for pattern, name in _OS_PATTERNS if pattern.search(user_agent)), None)

    if browser and os_name:
        return f"{browser} on {os_name}"
    if browser:
        return browser
    if os_name:
        return os_name
    return "Unknown device"


async def _count_active_sessions(db: AsyncSession, user_id: uuid.UUID) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(func.count())
        .select_from(Session)
        .where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
    )
    return result.scalar_one()


async def create_session(
    db: AsyncSession, user_id: uuid.UUID, user_agent: str | None
) -> Session:
    """Raises ForbiddenError if the account is already at its concurrent
    device limit — caller must revoke a session before logging in again."""
    active_count = await _count_active_sessions(db, user_id)
    if active_count >= settings.max_active_sessions_per_user:
        raise ForbiddenError(
            f"You're signed in on {settings.max_active_sessions_per_user} devices already. "
            "Log out from another device to continue."
        )

    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    session = Session(
        user_id=user_id,
        device_label=device_label_from_user_agent(user_agent),
        expires_at=expires_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_active_session(db: AsyncSession, session_id: uuid.UUID) -> Session | None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def list_active_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[Session]:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Session)
        .where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
        .order_by(Session.created_at.desc())
    )
    return list(result.scalars())


async def revoke_session(db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    """Scoped to user_id so a user can only ever revoke their own sessions."""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session or session.revoked_at is not None:
        raise NotFoundError("Session not found")
    session.revoked_at = datetime.now(timezone.utc)
    await db.commit()


async def require_active_session(db: AsyncSession, session_id_raw: str | None) -> uuid.UUID:
    """Validate the 'sid' claim from a decoded access token against the DB.
    Raising here (rather than just trusting the JWT) is what makes logout
    and the device limit take effect immediately instead of waiting up to
    ACCESS_TOKEN_EXPIRE_MINUTES for the token to expire on its own."""
    if not session_id_raw:
        raise UnauthorizedError("Invalid token payload")
    try:
        session_id = uuid.UUID(session_id_raw)
    except ValueError:
        raise UnauthorizedError("Invalid token payload")

    session = await get_active_session(db, session_id)
    if not session:
        raise UnauthorizedError("Session has been revoked. Please log in again.")
    return session_id
