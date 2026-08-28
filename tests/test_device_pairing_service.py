"""Pairing-code lifecycle: pending -> confirmed -> consumed, and expiry."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import NotFoundError
from app.models.device_pairing_code import DevicePairingCode
from app.services.device_pairing import poll_pairing


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class FakeDb:
    """Returns queued results in order, one per execute() call."""

    def __init__(self, results):
        self._results = list(results)
        self.committed = False

    async def execute(self, _stmt):
        return self._results.pop(0)

    async def commit(self):
        self.committed = True


def _pairing(status: str, **overrides) -> DevicePairingCode:
    defaults = dict(
        id=uuid.uuid4(),
        code_hash="irrelevant-in-these-tests",
        status=status,
        token=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    defaults.update(overrides)
    return DevicePairingCode(**defaults)


def test_poll_pending_code_returns_pending_without_committing():
    pairing = _pairing("pending")
    db = FakeDb([FakeResult(scalar=pairing)])

    result = asyncio.run(poll_pairing(db, "raw-code"))

    assert result == {"status": "pending"}
    assert db.committed is False


def test_poll_confirmed_code_returns_token_and_consumes_it():
    pairing = _pairing("confirmed", token="jwt-token-value")
    db = FakeDb([FakeResult(scalar=pairing)])

    result = asyncio.run(poll_pairing(db, "raw-code"))

    assert result == {"status": "confirmed", "access_token": "jwt-token-value"}
    # Single-use: a second poll must not be able to replay the same token.
    assert pairing.status == "expired"
    assert db.committed is True


def test_poll_past_expiry_raises_not_found_even_if_still_pending():
    pairing = _pairing("pending", expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    db = FakeDb([FakeResult(scalar=pairing)])

    with pytest.raises(NotFoundError):
        asyncio.run(poll_pairing(db, "raw-code"))


def test_poll_unknown_code_raises_not_found():
    db = FakeDb([FakeResult(scalar=None)])

    with pytest.raises(NotFoundError):
        asyncio.run(poll_pairing(db, "raw-code"))


def test_poll_confirmed_code_cannot_be_replayed_after_first_consumption():
    pairing = _pairing("confirmed", token="jwt-token-value")
    db = FakeDb([FakeResult(scalar=pairing), FakeResult(scalar=pairing)])

    first = asyncio.run(poll_pairing(db, "raw-code"))
    assert first == {"status": "confirmed", "access_token": "jwt-token-value"}

    with pytest.raises(NotFoundError):
        asyncio.run(poll_pairing(db, "raw-code"))
