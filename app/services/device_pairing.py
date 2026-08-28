"""TV QR sign-in: short-lived pairing codes.

The TV calls start_pairing() and poll_pairing(); the phone browser (already
authenticated via the normal /auth/login or /auth/register flow) calls
confirm_pairing(). See docs/superpowers/specs/2026-08-28-tv-device-pairing-design.md.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.security import (
    create_access_token,
    generate_reset_token,
    hash_reset_token,
)
from app.models.device_pairing_code import DevicePairingCode
from app.models.user import User
from app.services.session import create_session

settings = get_settings()


async def start_pairing(db: AsyncSession) -> tuple[str, int]:
    """Create a pending pairing code. Returns (raw_code, expires_in_seconds)."""
    raw_code, code_hash = generate_reset_token()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.device_pairing_code_expire_minutes
    )
    db.add(DevicePairingCode(code_hash=code_hash, expires_at=expires_at))
    await db.commit()
    return raw_code, settings.device_pairing_code_expire_minutes * 60


async def _find_pending_or_confirmed(
    db: AsyncSession, raw_code: str
) -> DevicePairingCode:
    code_hash = hash_reset_token(raw_code)
    result = await db.execute(
        select(DevicePairingCode)
        .where(DevicePairingCode.code_hash == code_hash)
        .with_for_update()
    )
    pairing = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if (
        not pairing
        or pairing.expires_at < now
        or pairing.status not in ("pending", "confirmed")
    ):
        raise NotFoundError("This code has expired.")
    return pairing


async def confirm_pairing(
    db: AsyncSession, raw_code: str, user: User, user_agent: str | None
) -> None:
    """Called by the already-authenticated phone browser. Raises ForbiddenError
    (propagated from create_session) if the user is already at their
    concurrent-device limit."""
    pairing = await _find_pending_or_confirmed(db, raw_code)
    if pairing.status != "pending":
        raise NotFoundError("This code has expired.")

    session = await create_session(db, user.id, user_agent)
    pairing.token = create_access_token(user.id, user.role, session.id)
    pairing.user_id = user.id
    pairing.status = "confirmed"
    await db.commit()


async def poll_pairing(db: AsyncSession, raw_code: str) -> dict:
    """Called by the TV. A confirmed code is consumed (marked expired) on the
    first successful poll so the token can't be replayed."""
    pairing = await _find_pending_or_confirmed(db, raw_code)
    if pairing.status == "pending":
        return {"status": "pending"}

    token = pairing.token
    pairing.status = "expired"
    pairing.token = None
    await db.commit()
    return {"status": "confirmed", "access_token": token}
