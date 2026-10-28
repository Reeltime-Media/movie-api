"""Phone sign-in through the Telegram bot: Start → Confirm → app poll."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.config import clear_settings_cache
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.core.security import hash_reset_token
from app.dependencies.db import get_db
from app.models.telegram_bot_login import TelegramBotLogin
from app.routers import telegram_webhook
from app.services import telegram_bot_login as bot_login


class FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class FakeDb:
    def __init__(self, row: TelegramBotLogin | None = None):
        self.row = row
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, *_a, **_k):
        return FakeResult(self.row)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None


@pytest.fixture
def bot_calls(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_call(method, payload):
        calls.append((method, payload))
        return True

    monkeypatch.setattr(bot_login, "call_bot_api", fake_call)
    monkeypatch.setattr(bot_login.settings, "telegram_bot_token", "123456:ABC-DEF")
    monkeypatch.setattr(bot_login.settings, "telegram_bot_username", "@reeltime_bot")
    monkeypatch.setattr(bot_login.settings, "telegram_webhook_secret", "hook-secret")
    return calls


def _row(status="pending", telegram_id=None, minutes=5) -> TelegramBotLogin:
    return TelegramBotLogin(
        id=uuid.uuid4(),
        code_hash=hash_reset_token("raw-code"),
        status=status,
        telegram_id=telegram_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=minutes),
    )


def _start_update(sender_id=42, text="/start login-raw-code", chat_type="private"):
    return {
        "update_id": 1,
        "message": {
            "message_id": 7,
            "chat": {"id": sender_id, "type": chat_type},
            "from": {"id": sender_id, "is_bot": False, "first_name": "Reel", "username": "reel"},
            "text": text,
        },
    }


def _callback_update(row: TelegramBotLogin, sender_id=42, prefix=bot_login.CONFIRM_PREFIX):
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": sender_id},
            "data": f"{prefix}{row.id}",
            "message": {"message_id": 8, "chat": {"id": sender_id}},
        },
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/start login-abc_DEF-1", "abc_DEF-1"),
        ("/start@reeltime_bot login-abc", "abc"),
        ("/start", None),
        ("/start other-payload", None),
        ("/start login-", None),
        ("hello", None),
        (None, None),
    ],
)
def test_parse_login_start(text, expected):
    assert bot_login.parse_login_start(text) == expected


def test_start_requires_webhook_secret(monkeypatch, bot_calls):
    monkeypatch.setattr(bot_login.settings, "telegram_webhook_secret", "")
    with pytest.raises(UnauthorizedError):
        asyncio.run(bot_login.start_bot_login(FakeDb()))


def test_start_stores_only_the_hash_and_builds_links(bot_calls):
    db = FakeDb()
    code, url, app_url, expires_in = asyncio.run(bot_login.start_bot_login(db))
    (row,) = db.added
    assert row.code_hash == hash_reset_token(code)
    assert url == f"https://t.me/reeltime_bot?start=login-{code}"
    assert app_url == f"tg://resolve?domain=reeltime_bot&start=login-{code}"
    # Telegram caps the start parameter at 64 chars of [A-Za-z0-9_-].
    assert len(f"login-{code}") <= 64
    assert expires_in == bot_login.settings.telegram_bot_login_expire_minutes * 60


def test_start_message_records_identity_and_asks_to_confirm(bot_calls):
    row = _row()
    asyncio.run(bot_login.handle_update(FakeDb(row), _start_update()))
    assert row.status == "started"
    assert row.telegram_id == "42"
    assert row.telegram_first_name == "Reel"
    method, payload = bot_calls[-1]
    assert method == "sendMessage"
    buttons = payload["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == f"{bot_login.CONFIRM_PREFIX}{row.id}"
    assert len(buttons[0]["callback_data"].encode()) <= 64


def test_someone_else_cannot_take_over_a_started_code(bot_calls):
    row = _row(status="started", telegram_id="42")
    asyncio.run(bot_login.handle_update(FakeDb(row), _start_update(sender_id=99)))
    assert row.telegram_id == "42"
    assert bot_calls[-1][1]["text"] == bot_login._EXPIRED_TEXT


def test_expired_code_is_rejected(bot_calls):
    row = _row(minutes=-1)
    asyncio.run(bot_login.handle_update(FakeDb(row), _start_update()))
    assert row.status == "pending"
    assert bot_calls[-1][1]["text"] == bot_login._EXPIRED_TEXT


def test_group_chats_are_ignored(bot_calls):
    row = _row()
    asyncio.run(bot_login.handle_update(FakeDb(row), _start_update(chat_type="group")))
    assert row.status == "pending"
    assert bot_calls == []


def test_confirm_by_the_same_user(bot_calls):
    row = _row(status="started", telegram_id="42")
    asyncio.run(bot_login.handle_update(FakeDb(row), _callback_update(row)))
    assert row.status == "confirmed"
    assert [m for m, _ in bot_calls] == ["answerCallbackQuery", "editMessageText"]


def test_confirm_by_another_user_is_ignored(bot_calls):
    row = _row(status="started", telegram_id="42")
    asyncio.run(bot_login.handle_update(FakeDb(row), _callback_update(row, sender_id=99)))
    assert row.status == "started"


def test_cancel_expires_the_code(bot_calls):
    row = _row(status="started", telegram_id="42")
    update = _callback_update(row, prefix=bot_login.CANCEL_PREFIX)
    asyncio.run(bot_login.handle_update(FakeDb(row), update))
    assert row.status == "expired"


@pytest.mark.parametrize("status", ["pending", "started"])
def test_poll_reports_progress(status):
    row = _row(status=status, telegram_id="42" if status == "started" else None)
    assert asyncio.run(bot_login.poll_bot_login(FakeDb(row), "raw-code")) == {"status": status}


@pytest.mark.parametrize("status", ["used", "expired"])
def test_poll_rejects_spent_codes(status):
    with pytest.raises(NotFoundError):
        asyncio.run(bot_login.poll_bot_login(FakeDb(_row(status=status)), "raw-code"))


def test_poll_rejects_unknown_code():
    with pytest.raises(NotFoundError):
        asyncio.run(bot_login.poll_bot_login(FakeDb(None), "nope"))


def test_poll_hands_out_the_token_once(monkeypatch):
    row = _row(status="confirmed", telegram_id="42")
    row.telegram_first_name = "Reel"
    seen = {}

    async def fake_login(_db, **kwargs):
        seen.update(kwargs)
        return object(), "jwt-token"

    monkeypatch.setattr(bot_login, "login_telegram_identity", fake_login)
    result = asyncio.run(bot_login.poll_bot_login(FakeDb(row), "raw-code", "ua", "guest-1"))
    assert result == {"status": "confirmed", "access_token": "jwt-token"}
    assert row.status == "used"
    assert seen["telegram_id"] == "42"
    assert seen["guest_id"] == "guest-1"


@pytest.fixture
def webhook_client(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "hook-secret")
    clear_settings_cache()
    handled: list[dict] = []

    async def fake_handle(_db, update):
        handled.append(update)

    async def fake_db():
        yield FakeDb()

    monkeypatch.setattr(telegram_webhook, "handle_update", fake_handle)
    app_main.app.dependency_overrides[get_db] = fake_db
    app_main.app.state.db_ready = True
    yield TestClient(app_main.app), handled
    app_main.app.dependency_overrides.pop(get_db, None)


def test_webhook_rejects_a_wrong_secret(webhook_client):
    client, handled = webhook_client
    res = client.post(
        "/webhooks/telegram",
        json=_start_update(),
        headers={"X-Telegram-Bot-Api-Secret-Token": "guess"},
    )
    assert res.status_code == 401
    assert handled == []


def test_webhook_accepts_the_registered_secret(webhook_client):
    client, handled = webhook_client
    res = client.post(
        "/webhooks/telegram",
        json=_start_update(),
        headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"},
    )
    assert res.status_code == 200
    assert handled == [_start_update()]


def test_webhook_is_off_without_a_secret(monkeypatch, webhook_client):
    client, _ = webhook_client
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "")
    clear_settings_cache()
    res = client.post("/webhooks/telegram", json={}, headers={})
    assert res.status_code == 503
