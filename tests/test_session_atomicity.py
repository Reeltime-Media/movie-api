"""Atomic session creation and password-reset session revocation."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.models.password_reset_token import PasswordResetToken
from app.models.session import Session
from app.models.user import User
from app.services import auth as auth_service
from app.services import session as session_service


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _RecordingDb:
    def __init__(self, *, user=None, active_count=0, reset_token=None):
        self.user = user
        self.active_count = active_count
        self.reset_token = reset_token
        self.added: list = []
        self.committed = False
        self.flushed = False
        self.execute_stmts: list = []
        self._execute_i = 0

    async def execute(self, stmt):
        self.execute_stmts.append(stmt)
        compiled = str(
            stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False})
        )
        upper = compiled.upper()
        # User lock / get
        if "FROM USERS" in upper or "FROM users" in compiled:
            return _ScalarResult(self.user)
        # Active session count
        if "COUNT" in upper:
            return _ScalarResult(self.active_count)
        # Password reset token
        if "PASSWORD_RESET" in upper or "password_reset" in compiled:
            return _ScalarResult(self.reset_token)
        # Session revoke update — no result needed
        if "UPDATE" in upper and "SESSIONS" in upper:
            return _ScalarResult(None)
        return _ScalarResult(None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True
        for obj in self.added:
            if isinstance(obj, Session) and getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, obj):
        if isinstance(obj, Session) and getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def get(self, model, pk):
        if model is User and self.user and self.user.id == pk:
            return self.user
        return None


def test_create_session_flushes_without_committing():
    user = User(
        id=uuid.uuid4(),
        email="a@example.com",
        role="user",
        is_active=True,
    )
    db = _RecordingDb(user=user, active_count=0)

    session = asyncio.run(session_service.create_session(db, user.id, "Chrome on iOS"))

    assert isinstance(session, Session)
    assert db.flushed is True
    assert db.committed is False
    assert any(isinstance(o, Session) for o in db.added)


def test_create_session_locks_user_row():
    user = User(
        id=uuid.uuid4(),
        email="a@example.com",
        role="user",
        is_active=True,
    )
    db = _RecordingDb(user=user, active_count=0)

    asyncio.run(session_service.create_session(db, user.id, None))

    user_lock_stmts = [
        str(s.compile(dialect=postgresql.dialect())).upper()
        for s in db.execute_stmts
        if "USERS" in str(s.compile(dialect=postgresql.dialect())).upper()
    ]
    assert user_lock_stmts, "expected a users query"
    assert any("FOR UPDATE" in s for s in user_lock_stmts)


def test_create_session_enforces_device_limit(monkeypatch):
    monkeypatch.setattr(session_service.settings, "max_active_sessions_per_user", 2)
    user = User(
        id=uuid.uuid4(),
        email="a@example.com",
        role="user",
        is_active=True,
    )
    db = _RecordingDb(user=user, active_count=2)

    with pytest.raises(ForbiddenError):
        asyncio.run(session_service.create_session(db, user.id, None))
    assert db.committed is False


@pytest.mark.asyncio
async def test_reset_password_locks_token_and_revokes_sessions(monkeypatch):
    user = User(
        id=uuid.uuid4(),
        email="a@example.com",
        role="user",
        is_active=True,
        password_hash="old",
    )
    token = PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash="hashed",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        used_at=None,
    )
    db = _RecordingDb(user=user, reset_token=token)
    revoked = {}

    async def fake_revoke(db_arg, user_id):
        revoked["user_id"] = user_id

    monkeypatch.setattr(auth_service, "hash_reset_token", lambda t: "hashed")

    async def fake_hash(_password: str) -> str:
        return "new-hash"

    monkeypatch.setattr(auth_service, "hash_password_async", fake_hash)
    monkeypatch.setattr(auth_service, "revoke_all_user_sessions", fake_revoke)

    await auth_service.reset_password(db, "raw-token", "NewPassword123!")

    assert token.used_at is not None
    assert user.password_hash == "new-hash"
    assert revoked["user_id"] == user.id
    assert db.committed is True

    token_stmts = [
        str(s.compile(dialect=postgresql.dialect())).upper()
        for s in db.execute_stmts
        if "PASSWORD_RESET" in str(s.compile(dialect=postgresql.dialect())).upper()
        or "password_reset" in str(s.compile(dialect=postgresql.dialect()))
    ]
    assert any("FOR UPDATE" in s for s in token_stmts)


@pytest.mark.asyncio
async def test_reset_password_rejects_used_token(monkeypatch):
    user = User(
        id=uuid.uuid4(),
        email="a@example.com",
        role="user",
        is_active=True,
    )
    token = PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash="hashed",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        used_at=datetime.now(UTC),
    )
    db = _RecordingDb(user=user, reset_token=token)
    monkeypatch.setattr(auth_service, "hash_reset_token", lambda t: "hashed")

    with pytest.raises(UnauthorizedError):
        await auth_service.reset_password(db, "raw-token", "NewPassword123!")
    assert db.committed is False
