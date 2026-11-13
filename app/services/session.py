import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import create_access_token, decode_expired_access_token
from app.models.session import Session
from app.models.user import User

settings = get_settings()

# How long the token a refresh replaced may still refresh, so a lost response
# or two tabs refreshing together don't sign the device out.
REFRESH_RETRY_WINDOW = timedelta(minutes=2)

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

    browser = next(
        (name for pattern, name in _BROWSER_PATTERNS if pattern.search(user_agent)), None
    )
    os_name = next((name for pattern, name in _OS_PATTERNS if pattern.search(user_agent)), None)

    if browser and os_name:
        return f"{browser} on {os_name}"
    if browser:
        return browser
    if os_name:
        return os_name
    return "Unknown device"


async def _count_active_sessions(db: AsyncSession, user_id: uuid.UUID) -> int:
    now = datetime.now(UTC)
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


async def create_session(db: AsyncSession, user_id: uuid.UUID, user_agent: str | None) -> Session:
    """Create a session row. Caller owns the transaction commit.

    Locks the user row so concurrent logins / pairing confirms cannot each
    observe the same active-session count and exceed the device limit.
    Flushes (does not commit) so device pairing can confirm the code in the
    same transaction as the session insert.
    """
    locked = await db.execute(select(User).where(User.id == user_id).with_for_update())
    if locked.scalar_one_or_none() is None:
        raise NotFoundError("User not found")

    active_count = await _count_active_sessions(db, user_id)
    if active_count >= settings.max_active_sessions_per_user:
        raise ForbiddenError(
            f"You're signed in on {settings.max_active_sessions_per_user} devices already. "
            "Log out from another device to continue."
        )

    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    session = Session(
        user_id=user_id,
        device_label=device_label_from_user_agent(user_agent),
        expires_at=expires_at,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def get_active_session(db: AsyncSession, session_id: uuid.UUID) -> Session | None:
    now = datetime.now(UTC)
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


def _refresh_cutoff(now: datetime) -> datetime | None:
    """Sessions that lapsed at or before this can no longer refresh; None means never."""
    if settings.session_refresh_grace_days is None:
        return None
    return now - timedelta(days=settings.session_refresh_grace_days)


async def list_active_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[Session]:
    """Every session that can still be used, including idle ones that only need
    POST /auth/refresh, so a device left signed in can always be revoked."""
    stmt = select(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    cutoff = _refresh_cutoff(datetime.now(UTC))
    if cutoff is not None:
        stmt = stmt.where(Session.expires_at > cutoff)
    result = await db.execute(stmt.order_by(Session.created_at.desc()))
    return list(result.scalars())


async def revoke_session(db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    """Scoped to user_id so a user can only ever revoke their own sessions."""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session or session.revoked_at is not None:
        raise NotFoundError("Session not found")
    session.revoked_at = datetime.now(UTC)
    await db.commit()


async def refresh_session(db: AsyncSession, token: str) -> str:
    """Exchange a token whose session is still alive for a new one.

    The JWT may already be expired; the session row decides. A revoked session
    never refreshes, and one that lapsed past the grace window needs a login.

    Each refresh moves the session to a new token version. Only a token at the
    current version may refresh, so once the device refreshes, a copy of an
    older token is useless; presenting one revokes the session. The one
    exception is the token a refresh just replaced when its successor never
    reached the server: the device lost that response (app killed, network
    dropped), so the old token is still its own and gets the current one back.
    """
    payload = decode_expired_access_token(token)
    try:
        session_id = uuid.UUID(payload.get("sid") or "")
        user_id = uuid.UUID(payload.get("sub") or "")
        # Tokens issued before rotation carry no version; sessions start at 0.
        version = int(payload.get("ver", 0))
    except (TypeError, ValueError):
        raise UnauthorizedError("Invalid token payload")

    now = datetime.now(UTC)
    # Locked so two refreshes of the same token see each other's version bump.
    result = await db.execute(
        select(Session)
        .where(Session.id == session_id, Session.revoked_at.is_(None))
        .with_for_update()
    )
    session = result.scalar_one_or_none()
    if not session or session.user_id != user_id:
        raise UnauthorizedError("Session has been revoked. Please log in again.")
    cutoff = _refresh_cutoff(now)
    if cutoff is not None and session.expires_at <= cutoff:
        raise UnauthorizedError("Session has expired. Please log in again.")

    current = session.token_version
    if version == current:
        next_version = current + 1
    elif version == current - 1 and (
        session.token_used_at is None
        or (session.refreshed_at is not None and now - session.refreshed_at < REFRESH_RETRY_WINDOW)
    ):
        # The same token refreshed moments ago (two tabs at once), or its
        # successor was never used (the response was lost). Hand back the
        # current token rather than signing out.
        next_version = current
    else:
        session.revoked_at = now
        await db.commit()
        raise UnauthorizedError("Session has been revoked. Please log in again.")

    # Locked like create_session, so a lapsed session and a new login can't
    # both take the last device slot.
    locked = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = locked.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or inactive")
    if (
        session.expires_at <= now
        and await _count_active_sessions(db, user_id) >= settings.max_active_sessions_per_user
    ):
        raise UnauthorizedError("Session has expired. Please log in again.")

    if next_version != current:
        session.token_version = next_version
        session.refreshed_at = now
        session.token_used_at = None
    session.expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    await db.commit()
    return create_access_token(user.id, user.role, session.id, next_version)


async def revoke_all_user_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Revoke every active session for a user. Caller owns the commit."""
    now = datetime.now(UTC)
    await db.execute(
        update(Session)
        .where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


async def require_active_session(
    db: AsyncSession, session_id_raw: str | None, version: int | None = None
) -> uuid.UUID:
    """Validate the 'sid' claim from a decoded access token against the DB.
    Raising here (rather than just trusting the JWT) is what makes logout
    and the device limit take effect immediately instead of waiting up to
    ACCESS_TOKEN_EXPIRE_MINUTES for the token to expire on its own.

    [version] is the token's 'ver' claim: the first request carrying the
    session's current version records that the device has that token, which
    is what lets refresh tell a lost response from a copied token."""
    if not session_id_raw:
        raise UnauthorizedError("Invalid token payload")
    try:
        session_id = uuid.UUID(session_id_raw)
    except ValueError:
        raise UnauthorizedError("Invalid token payload")

    session = await get_active_session(db, session_id)
    if not session:
        raise UnauthorizedError("Session has been revoked. Please log in again.")
    if version == session.token_version and session.token_used_at is None:
        # Once per refresh, and before the handler runs, so nothing else is
        # pending in this transaction yet.
        await db.execute(
            update(Session)
            .where(
                Session.id == session_id,
                Session.token_version == version,
                Session.token_used_at.is_(None),
            )
            .values(token_used_at=datetime.now(UTC))
        )
        await db.commit()
    return session_id
