"""Admin-issued TV unlock IDs.

Each code owns a synthetic user + active subscription whose
`current_period_end` matches `expires_at`. Entering the ID on TV returns a
normal JWT, so existing entitlement checks unlock all content until expiry.
"""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import create_access_token, hash_password
from app.models.session import Session
from app.models.subscription import Subscription
from app.models.tv_access_code import TvAccessCode
from app.models.user import User
from app.schemas.tv_access_code import (
    TvAccessCodeCreate,
    TvAccessCodeRead,
    TvAccessCodeUpdate,
)
from app.services.session import create_session

_TV_PLAN = "tv_access"
_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_expired(row: TvAccessCode, *, now: datetime | None = None) -> bool:
    stamp = now or _utcnow()
    return _ensure_aware(row.expires_at) <= stamp


def to_read(row: TvAccessCode) -> TvAccessCodeRead:
    return TvAccessCodeRead(
        id=row.id,
        code=row.code,
        label=row.label,
        user_id=row.user_id,
        expires_at=row.expires_at,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        is_expired=_is_expired(row),
    )


def _generate_code() -> str:
    body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"TV-{body}"


async def _unique_code(db: AsyncSession, preferred: str | None) -> str:
    if preferred:
        existing = await db.execute(
            select(TvAccessCode.id).where(TvAccessCode.code == preferred)
        )
        if existing.scalar_one_or_none():
            raise ConflictError("This TV ID is already in use")
        return preferred

    for _ in range(12):
        candidate = _generate_code()
        existing = await db.execute(
            select(TvAccessCode.id).where(TvAccessCode.code == candidate)
        )
        if existing.scalar_one_or_none() is None:
            return candidate
    raise ConflictError("Could not generate a unique TV ID. Try again.")


async def list_tv_access_codes(db: AsyncSession) -> list[TvAccessCodeRead]:
    result = await db.execute(
        select(TvAccessCode).order_by(TvAccessCode.created_at.desc())
    )
    return [to_read(row) for row in result.scalars()]


async def create_tv_access_code(
    db: AsyncSession, data: TvAccessCodeCreate
) -> TvAccessCodeRead:
    expires_at = _ensure_aware(data.expires_at)
    if expires_at <= _utcnow():
        raise ConflictError("Expiry must be in the future")

    code = await _unique_code(db, data.code)
    email = f"tv+{code.lower().replace('-', '')}@tv.reeltime.local"
    user = User(
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        full_name=data.label or f"TV {code}",
        role="user",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    now = _utcnow()
    subscription = Subscription(
        user_id=user.id,
        plan=_TV_PLAN,
        status="active" if data.is_active else "cancelled",
        current_period_start=now,
        current_period_end=expires_at,
    )
    db.add(subscription)

    row = TvAccessCode(
        code=code,
        label=data.label,
        user_id=user.id,
        expires_at=expires_at,
        is_active=data.is_active,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return to_read(row)


async def _get_row(db: AsyncSession, code_id: uuid.UUID) -> TvAccessCode:
    result = await db.execute(select(TvAccessCode).where(TvAccessCode.id == code_id))
    row = result.scalar_one_or_none()
    if not row:
        raise NotFoundError("TV access ID not found")
    return row


async def update_tv_access_code(
    db: AsyncSession, code_id: uuid.UUID, data: TvAccessCodeUpdate
) -> TvAccessCodeRead:
    row = await _get_row(db, code_id)
    payload = data.model_dump(exclude_unset=True)

    if "label" in payload:
        row.label = payload["label"]
        user_result = await db.execute(select(User).where(User.id == row.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.full_name = row.label or f"TV {row.code}"

    if "expires_at" in payload and payload["expires_at"] is not None:
        expires_at = _ensure_aware(payload["expires_at"])
        row.expires_at = expires_at
        await db.execute(
            update(Subscription)
            .where(
                Subscription.user_id == row.user_id,
                Subscription.plan == _TV_PLAN,
            )
            .values(current_period_end=expires_at)
        )

    if "is_active" in payload and payload["is_active"] is not None:
        row.is_active = bool(payload["is_active"])
        status = "active" if row.is_active and not _is_expired(row) else "cancelled"
        await db.execute(
            update(Subscription)
            .where(
                Subscription.user_id == row.user_id,
                Subscription.plan == _TV_PLAN,
            )
            .values(status=status)
        )
        user_result = await db.execute(select(User).where(User.id == row.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.is_active = row.is_active

    await db.commit()
    await db.refresh(row)
    return to_read(row)


async def delete_tv_access_code(db: AsyncSession, code_id: uuid.UUID) -> None:
    row = await _get_row(db, code_id)
    user_result = await db.execute(select(User).where(User.id == row.user_id))
    user = user_result.scalar_one_or_none()
    # Deleting the user cascades the tv_access_codes + subscriptions rows.
    if user:
        await db.delete(user)
    else:
        await db.delete(row)
    await db.commit()


async def _revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    now = _utcnow()
    await db.execute(
        update(Session)
        .where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.commit()


async def login_with_tv_access_code(
    db: AsyncSession,
    raw_code: str,
    user_agent: str | None = None,
) -> str:
    code = raw_code.strip().upper()
    result = await db.execute(select(TvAccessCode).where(TvAccessCode.code == code))
    row = result.scalar_one_or_none()
    if not row or not row.is_active:
        raise UnauthorizedError("Invalid or inactive TV ID")
    if _is_expired(row):
        raise UnauthorizedError("This TV ID has expired. Ask admin for a new one.")

    user_result = await db.execute(select(User).where(User.id == row.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("Invalid or inactive TV ID")

    # Keep subscription end in sync if admin extended expiry after cancel.
    await db.execute(
        update(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.plan == _TV_PLAN,
        )
        .values(
            status="active",
            current_period_end=_ensure_aware(row.expires_at),
        )
    )
    await db.commit()

    # One active TV box per ID — re-login on a new TV kicks the previous one.
    await _revoke_all_sessions(db, user.id)
    session = await create_session(db, user.id, user_agent or "REELTIME TV")
    return create_access_token(user.id, user.role, session.id)
