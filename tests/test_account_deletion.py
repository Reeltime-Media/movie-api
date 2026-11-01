"""Self-service deletion: personal data goes, payment records stay."""

import asyncio
import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import ForbiddenError
from app.main import app
from app.models.user import User
from app.services.account import delete_user_account


class _RecordingDb:
    def __init__(self):
        self.sql: list[str] = []
        self.committed = False

    async def execute(self, stmt):
        self.sql.append(str(stmt.compile(dialect=postgresql.dialect())))

    async def commit(self):
        self.committed = True


def _user(**overrides) -> User:
    values = {
        "id": uuid.uuid4(),
        "email": "viewer@example.com",
        "password_hash": "hash",
        "google_id": "google-1",
        "telegram_id": "telegram-1",
        "apple_id": "apple-1",
        "avatar_url": "https://example.com/a.png",
        "full_name": "A Viewer",
        "role": "user",
        "is_active": True,
    }
    return User(**{**values, **overrides})


def test_delete_removes_identity_from_the_user_row():
    db = _RecordingDb()
    user = _user()

    asyncio.run(delete_user_account(db, user))

    assert "viewer@example.com" not in user.email
    assert user.password_hash is None
    assert user.google_id is None
    assert user.telegram_id is None
    assert user.apple_id is None
    assert user.avatar_url is None
    assert user.full_name is None
    assert user.is_active is False
    assert db.committed is True


def test_two_deleted_accounts_get_distinct_placeholder_emails():
    first, second = _user(), _user()

    asyncio.run(delete_user_account(_RecordingDb(), first))
    asyncio.run(delete_user_account(_RecordingDb(), second))

    assert first.email != second.email


@pytest.mark.parametrize(
    "table",
    [
        "watch_progress",
        "favorites",
        "ratings",
        "comment_votes",
        "comment_reports",
        "sessions",
        "tv_access_codes",
        "device_pairing_codes",
        "password_reset_tokens",
        "user_blocks",
    ],
)
def test_delete_clears_personal_tables(table):
    db = _RecordingDb()

    asyncio.run(delete_user_account(db, _user()))

    assert any(sql.startswith(f"DELETE FROM {table}") for sql in db.sql)


def test_delete_blanks_comments_so_replies_from_others_survive():
    db = _RecordingDb()

    asyncio.run(delete_user_account(db, _user()))

    assert any(sql.startswith("UPDATE comments") for sql in db.sql)
    assert not any(sql.startswith("DELETE FROM comments") for sql in db.sql)


@pytest.mark.parametrize("table", ["purchases", "payment_intents", "subscriptions"])
def test_delete_keeps_payment_records(table):
    db = _RecordingDb()

    asyncio.run(delete_user_account(db, _user()))

    assert not any(sql.startswith(f"DELETE FROM {table}") for sql in db.sql)


def test_admin_cannot_delete_their_own_account():
    db = _RecordingDb()

    with pytest.raises(ForbiddenError):
        asyncio.run(delete_user_account(db, _user(role="admin")))

    assert db.committed is False


def test_me_delete_route_is_registered():
    assert "delete" in app.openapi()["paths"]["/users/me"]
