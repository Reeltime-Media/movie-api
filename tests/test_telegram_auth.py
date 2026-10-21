"""Telegram Login Widget hash verification and account create/login."""

import asyncio
import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.exceptions import UnauthorizedError
from app.schemas.user import TelegramAuthRequest
from app.services import auth as auth_service


def _signed_payload(bot_token: str, **fields: str) -> dict[str, str]:
    rows = [f"{key}={value}" for key, value in sorted(fields.items())]
    secret = hashlib.sha256(bot_token.encode()).digest()
    digest = hmac.new(secret, "\n".join(rows).encode(), hashlib.sha256).hexdigest()
    return {**fields, "hash": digest}


def test_verify_telegram_login_hash_accepts_valid_signature():
    token = "123456:ABC-DEF"
    payload = _signed_payload(
        token,
        id="42",
        first_name="Bunk",
        auth_date="1710000000",
    )
    assert auth_service.verify_telegram_login_hash(payload, token) is True


def test_verify_telegram_login_hash_rejects_tampered_payload():
    token = "123456:ABC-DEF"
    payload = _signed_payload(
        token,
        id="42",
        first_name="Bunk",
        auth_date="1710000000",
    )
    payload["first_name"] = "Hacker"
    assert auth_service.verify_telegram_login_hash(payload, token) is False


def test_authenticate_telegram_rejects_stale_auth_date(monkeypatch):
    monkeypatch.setattr(auth_service.settings, "telegram_bot_token", "123456:ABC-DEF")
    monkeypatch.setattr(auth_service.settings, "telegram_bot_username", "reeltime_bot")
    monkeypatch.setattr(auth_service.settings, "telegram_auth_max_age_seconds", 60)

    stale = int(datetime.now(UTC).timestamp()) - 600
    data = TelegramAuthRequest(
        nonce="n1",
        id=42,
        first_name="Bunk",
        auth_date=stale,
        hash="deadbeef",
    )

    class FakeDb:
        async def execute(self, *_a, **_k):
            raise AssertionError("must not hit the database for stale auth")

    with pytest.raises(UnauthorizedError, match="expired"):
        asyncio.run(auth_service.authenticate_telegram(FakeDb(), data))


def test_authenticate_telegram_creates_active_account(monkeypatch):
    token = "123456:ABC-DEF"
    monkeypatch.setattr(auth_service.settings, "telegram_bot_token", token)
    monkeypatch.setattr(auth_service.settings, "telegram_bot_username", "reeltime_bot")
    monkeypatch.setattr(auth_service.settings, "telegram_auth_max_age_seconds", 300)

    auth_date = int(datetime.now(UTC).timestamp())
    signed = _signed_payload(
        token,
        id="99",
        first_name="Reel",
        last_name="Time",
        username="reeltime",
        auth_date=str(auth_date),
    )
    data = TelegramAuthRequest(
        nonce="nonce-raw",
        id=99,
        first_name="Reel",
        last_name="Time",
        username="reeltime",
        auth_date=auth_date,
        hash=signed["hash"],
    )

    created: list[object] = []

    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeDb:
        async def execute(self, *_a, **_k):
            return FakeResult()

        def add(self, obj):
            created.append(obj)

        async def flush(self):
            for obj in created:
                if getattr(obj, "id", None) is None:
                    obj.id = uuid.uuid4()
                if not getattr(obj, "role", None):
                    obj.role = "user"

        async def commit(self):
            return None

        async def refresh(self, _obj):
            return None

    async def fake_consume(_db, nonce):
        assert nonce == "nonce-raw"

    async def fake_claim(*_a, **_k):
        return None

    async def fake_session(_db, _user_id, _ua):
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(auth_service, "_consume_telegram_nonce", fake_consume)
    monkeypatch.setattr(auth_service, "claim_guest_purchases", fake_claim)
    monkeypatch.setattr(auth_service, "create_session", fake_session)
    monkeypatch.setattr(
        auth_service,
        "create_access_token",
        lambda *_a, **_k: "jwt-token",
    )

    user, access = asyncio.run(auth_service.authenticate_telegram(FakeDb(), data))
    assert access == "jwt-token"
    assert user.telegram_id == "99"
    assert user.email == "telegram_99@users.reeltime.fun"
    assert user.is_active is True
    assert user.full_name == "Reel Time"


def test_authenticate_telegram_rejects_bad_hash(monkeypatch):
    monkeypatch.setattr(auth_service.settings, "telegram_bot_token", "123456:ABC-DEF")
    monkeypatch.setattr(auth_service.settings, "telegram_bot_username", "reeltime_bot")
    monkeypatch.setattr(auth_service.settings, "telegram_auth_max_age_seconds", 300)

    data = TelegramAuthRequest(
        nonce="n1",
        id=1,
        first_name="X",
        auth_date=int(datetime.now(UTC).timestamp()),
        hash="not-a-real-hash",
    )

    class FakeDb:
        async def execute(self, *_a, **_k):
            raise AssertionError("must not consume nonce on bad hash")

    with pytest.raises(UnauthorizedError, match="Invalid Telegram"):
        asyncio.run(auth_service.authenticate_telegram(FakeDb(), data))
