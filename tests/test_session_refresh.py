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
from app.services.session import refresh_session, require_active_session


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
        self.updates = []

    async def execute(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
        if sql.startswith("update sessions"):
            self.updates.append(sql)
            return _Result(None)
        if "count(" in sql:
            return _Result(self.active_count)
        if "from sessions" in sql:
            filters_revoked = "revoked_at is null" in sql
            hidden = filters_revoked and self.session.revoked_at is not None
            return _Result(None if hidden else self.session)
        return _Result(self.user)

    async def commit(self):
        self.committed = True


def _token(*, user_id, session_id, expires_in=timedelta(hours=-2), secret=None, ver=None):
    settings = security.settings
    payload = {
        "sub": str(user_id),
        "role": "user",
        "sid": str(session_id),
        "exp": datetime.now(UTC) + expires_in,
    }
    if ver is not None:
        payload["ver"] = ver
    return jwt.encode(payload, secret or settings.secret_key, algorithm=settings.algorithm)


def _pair(
    *,
    session_expires_in=timedelta(hours=-2),
    revoked=False,
    is_active=True,
    token_version=0,
    refreshed_ago=None,
    token_used_ago=None,
):
    user = User(id=uuid.uuid4(), email="v@example.com", role="user", is_active=is_active)
    session = Session(
        id=uuid.uuid4(),
        user_id=user.id,
        device_label="Phone",
        expires_at=datetime.now(UTC) + session_expires_in,
        revoked_at=datetime.now(UTC) if revoked else None,
        token_version=token_version,
        refreshed_at=datetime.now(UTC) - refreshed_ago if refreshed_ago is not None else None,
        token_used_at=datetime.now(UTC) - token_used_ago if token_used_ago is not None else None,
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


def test_refresh_moves_the_session_to_a_new_token_version():
    user, session = _pair(token_version=3)
    db = _Db(session=session, user=user)

    fresh = asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id, ver=3)))

    assert decode_access_token(fresh)["ver"] == 4
    assert session.token_version == 4
    assert session.refreshed_at is not None


def test_a_new_token_starts_out_unused():
    user, session = _pair(token_version=3, token_used_ago=timedelta(minutes=30))
    db = _Db(session=session, user=user)

    asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id, ver=3)))

    assert session.token_used_at is None


def test_token_from_before_rotation_refreshes_a_fresh_session():
    user, session = _pair(token_version=0)
    db = _Db(session=session, user=user)

    fresh = asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id)))

    assert decode_access_token(fresh)["ver"] == 1


def test_replaced_token_retried_moments_later_gets_the_current_token():
    user, session = _pair(token_version=4, refreshed_ago=timedelta(seconds=20))
    db = _Db(session=session, user=user)

    fresh = asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id, ver=3)))

    assert decode_access_token(fresh)["ver"] == 4
    assert session.token_version == 4
    assert session.revoked_at is None


def test_replaced_token_after_the_window_revokes_once_its_successor_was_used():
    # The device used the new token, so whoever still holds the old one
    # copied it.
    user, session = _pair(
        token_version=4,
        refreshed_ago=timedelta(minutes=10),
        token_used_ago=timedelta(minutes=9),
    )
    db = _Db(session=session, user=user)

    with pytest.raises(UnauthorizedError):
        asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id, ver=3)))

    assert session.revoked_at is not None
    assert db.committed is True


def test_replaced_token_after_the_window_recovers_when_its_successor_never_arrived():
    # The device never got (or never kept) the token the refresh issued — the
    # app was killed or the response was lost — so the old token is still its
    # own. Hand back the current one instead of signing the device out.
    user, session = _pair(token_version=4, refreshed_ago=timedelta(hours=6))
    db = _Db(session=session, user=user)

    fresh = asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id, ver=3)))

    assert decode_access_token(fresh)["ver"] == 4
    assert session.token_version == 4
    assert session.revoked_at is None


def test_much_older_token_revokes_the_session():
    user, session = _pair(token_version=4, refreshed_ago=timedelta(seconds=5))
    db = _Db(session=session, user=user)

    with pytest.raises(UnauthorizedError):
        asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id, ver=1)))

    assert session.revoked_at is not None


def test_revoked_session_cannot_refresh():
    user, session = _pair(revoked=True)
    db = _Db(session=session, user=user)

    with pytest.raises(UnauthorizedError):
        asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id)))

    assert db.committed is False


def test_long_idle_session_still_refreshes_by_default():
    user, session = _pair(session_expires_in=timedelta(days=-400))
    db = _Db(session=session, user=user)

    token = asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id)))

    assert decode_access_token(token)["sid"] == str(session.id)


def test_session_past_a_configured_grace_window_cannot_refresh(monkeypatch):
    monkeypatch.setattr(session_service.settings, "session_refresh_grace_days", 30)
    user, session = _pair(session_expires_in=timedelta(days=-31))
    db = _Db(session=session, user=user)

    with pytest.raises(UnauthorizedError):
        asyncio.run(refresh_session(db, _token(user_id=user.id, session_id=session.id)))


def _listed_sql(monkeypatch, grace_days):
    monkeypatch.setattr(session_service.settings, "session_refresh_grace_days", grace_days)
    seen = []

    class _ListDb:
        async def execute(self, stmt):
            seen.append(str(stmt.compile(dialect=postgresql.dialect())).lower())
            return _Rows()

    class _Rows:
        def scalars(self):
            return []

    asyncio.run(session_service.list_active_sessions(_ListDb(), uuid.uuid4()))
    return seen[0]


def test_device_list_includes_idle_sessions_that_can_refresh(monkeypatch):
    sql = _listed_sql(monkeypatch, None)

    where = sql.split("where", 1)[1].split("order by")[0]
    assert "revoked_at is null" in where
    assert "expires_at" not in where


def test_device_list_drops_sessions_past_a_configured_grace_window(monkeypatch):
    assert "expires_at >" in _listed_sql(monkeypatch, 30)


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


def _live_pair(**kwargs):
    return _pair(session_expires_in=timedelta(minutes=30), **kwargs)


def test_request_with_the_newest_token_records_that_it_arrived():
    user, session = _live_pair(token_version=4)
    db = _Db(session=session, user=user)

    asyncio.run(require_active_session(db, str(session.id), version=4))

    assert len(db.updates) == 1
    assert "token_used_at" in db.updates[0]
    assert db.committed is True


def test_request_with_an_older_token_does_not_mark_the_newest_used():
    user, session = _live_pair(token_version=4)
    db = _Db(session=session, user=user)

    asyncio.run(require_active_session(db, str(session.id), version=3))

    assert db.updates == []


def test_newest_token_is_marked_used_only_once():
    user, session = _live_pair(token_version=4, token_used_ago=timedelta(minutes=1))
    db = _Db(session=session, user=user)

    asyncio.run(require_active_session(db, str(session.id), version=4))

    assert db.updates == []
    assert db.committed is False
