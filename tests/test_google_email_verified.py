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
