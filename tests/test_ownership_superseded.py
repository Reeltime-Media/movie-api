"""Ownership-only pending intents must not inflate succeeded revenue."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.billing.ownership import STATUS_SUPERSEDED, mark_succeeded_if_already_purchased


def _intent(**overrides):
    base = {
        "intent_id": "bkg-test",
        "user_id": uuid4(),
        "guest_id": None,
        "kind": "single",
        "content_id": uuid4(),
        "series_id": None,
        "status": "pending",
        "resolved_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_ownership_marks_superseded_not_succeeded():
    intent = _intent()
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = uuid4()  # existing purchase id
    db.execute.return_value = result

    assert await mark_succeeded_if_already_purchased(db, intent) is True
    assert intent.status == STATUS_SUPERSEDED
    assert intent.status != "succeeded"
    assert intent.resolved_at is not None
    assert intent.resolved_at.tzinfo is UTC


@pytest.mark.asyncio
async def test_ownership_no_purchase_leaves_pending():
    intent = _intent()
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    assert await mark_succeeded_if_already_purchased(db, intent) is False
    assert intent.status == "pending"
    assert intent.resolved_at is None
