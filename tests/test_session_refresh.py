"""POST /auth/refresh keeps a live session signed in past the JWT expiry."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy.dialects import postgresql

from app.core import security
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.main import app
from app.models.session import Session
from app.models.user import User
from app.services import session as session_service
from app.services.session import refresh_session


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _Db:
    def __init__(self, *, session, user, active_count=0):
        self.session = session
        self.user = user
        self.active_count = active_count
        self.committed = False

    async def execute(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
        if "count(" in sql:
            return _Result(self.active_count)
        if "from sessions" in sql:
            filters_revoked = "revoked_at is null" in sql
            hidden = filters_revoked and self.session.revoked_at is not None
            return _Result(None if hidden else self.session)
        return _Result(self.user)

    async def commit(self):
        self.committed = True


def _token(*, user_id, session_id, expires_in=timedelta(hours=-2), secret=None):
    settings = security.settings
    payload = {
        "sub": str(user_id),
        "role": "user",
        "sid": str(session_id),
        "exp": datetime.now(UTC) + expires_in,
    }
    return jwt.encode(payload, secret or settings.secret_key, algorithm=settings.algorithm)


def _pair(*, session_expires_in=timedelta(hours=-2), revoked=False, is_active=True):
    user = User(id=uuid.uuid4(), email="v@example.com", role="user", is_active=is_active)
    session = Session(
        id=uuid.uuid4(),
        user_id=user.id,
        device_label="Phone",
        expires_at=datetime.now(UTC) + session_expires_in,
        revoked_at=datetime.now(UTC) if revoked else None,
    )
    return user, session


def test_expired_token_on_a_live_session_gets_a_new_token():
    user, session = _pair()
    db = _Db(session=session, user=user)

    fresh = asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id)))

    claims = decode_access_token(fresh)
    assert claims["sid"] == str(session.id)
    assert claims["sub"] == str(user.id)
    assert session.expires_at > datetime.now(UTC)
    assert db.committed is True


def test_revoked_session_cannot_refresh():
    user, session = _pair(revoked=True)
    db = _Db(session=session, user=user)

    with pytest.raises(UnauthorizedError):
        asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id)))

    assert db.committed is False


def test_session_past_the_grace_window_cannot_refresh():
    user, session = _pair(session_expires_in=timedelta(days=-31))
    db = _Db(session=session, user=user)

    with pytest.raises(UnauthorizedError):
        asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id)))


def test_token_signed_with_another_key_cannot_refresh():
    user, session = _pair()
    db = _Db(session=session, user=user)
    forged = _token(
        user_id=user.id,
        session_id=session.id,
        secret="another-secret-key-thirty-two-characters",
    )

    with pytest.raises(UnauthorizedError):
        asyncio.run(refresh_session(db, forged))


def test_token_for_another_user_cannot_refresh_this_session():
    user, session = _pair()
    db = _Db(session=session, user=user)

    with pytest.raises(UnauthorizedError):
        asyncio.run(refresh_session(db, _token(user_id=uuid.uuid4(), session_id=session.id)))


def test_disabled_user_cannot_refresh():
    user, session = _pair(is_active=False)
    db = _Db(session=session, user=user)

    with pytest.raises(UnauthorizedError):
        asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id)))


def test_lapsed_session_cannot_take_a_device_slot_that_is_already_full():
    user, session = _pair()
    limit = session_service.settings.max_active_sessions_per_user
    db = _Db(session=session, user=user, active_count=limit)

    with pytest.raises(UnauthorizedError):
        asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id)))


def test_live_session_at_the_device_limit_can_still_refresh():
    user, session = _pair(session_expires_in=timedelta(minutes=5))
    limit = session_service.settings.max_active_sessions_per_user
    db = _Db(session=session, user=user, active_count=limit)

    fresh = asyncio.run(
        refresh_session(
            db,
            _token(user_id=user.id, session_id=session.id, expires_in=timedelta(minutes=5)),
        )
    )

    assert decode_access_token(fresh)["sid"] == str(session.id)


def test_refresh_route_is_registered():
    assert "post" in app.openapi()["paths"]["/auth/refresh"]
