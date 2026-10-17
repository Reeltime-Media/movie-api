"""Google Sign-In must require a verified email claim."""

import pytest

from app.core.exceptions import UnauthorizedError
from app.services import auth as auth_service


def test_authenticate_google_rejects_unverified_email(monkeypatch):
    monkeypatch.setattr(
        auth_service,
        "_verify_google_id_token",
        lambda _token: {
            "sub": "google-sub-1",
            "email": "user@example.com",
            "email_verified": False,
        },
    )

    async def boom(*_a, **_k):
        raise AssertionError("must not hit the database")

    class FakeDb:
        execute = boom

    with pytest.raises(UnauthorizedError, match="not verified"):
        import asyncio

        asyncio.run(auth_service.authenticate_google(FakeDb(), id_token="tok"))


def test_authenticate_google_rejects_missing_email_verified(monkeypatch):
    monkeypatch.setattr(
        auth_service,
        "_verify_google_id_token",
        lambda _token: {"sub": "google-sub-1", "email": "user@example.com"},
    )

    class FakeDb:
        async def execute(self, *_a, **_k):
            raise AssertionError("must not hit the database")

    with pytest.raises(UnauthorizedError, match="not verified"):
        import asyncio

        asyncio.run(auth_service.authenticate_google(FakeDb(), id_token="tok"))


def test_authenticate_google_creates_active_account_for_new_user(monkeypatch):
    """A first-time Google user must not be rejected as "Account is disabled".

    The column default for is_active only applies at INSERT, so the new User
    must be created active explicitly before the is_active check runs.
    """
    import asyncio
    import uuid
    from types import SimpleNamespace

    monkeypatch.setattr(
        auth_service,
        "_verify_google_id_token",
        lambda _token: {
            "sub": "google-sub-new",
            "email": "New.User@gmail.com",
            "email_verified": True,
            "name": "New User",
        },
    )

    async def fake_create_session(_db, user_id, _user_agent):
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(auth_service, "create_session", fake_create_session)
    monkeypatch.setattr(auth_service, "create_access_token", lambda *_a: "token")

    class NoRows:
        def scalar_one_or_none(self):
            return None

    class FakeDb:
        def __init__(self):
            self.added = []

        async def execute(self, *_a, **_k):
            return NoRows()

        def add(self, obj):
            self.added.append(obj)

        async def flush(self):
            pass

        async def commit(self):
            pass

        async def refresh(self, _obj):
            pass

    db = FakeDb()
    user, token = asyncio.run(auth_service.authenticate_google(db, id_token="tok"))

    assert token == "token"
    assert db.added == [user]
    assert user.is_active is True
    assert user.email == "new.user@gmail.com"
    assert user.google_id == "google-sub-new"
