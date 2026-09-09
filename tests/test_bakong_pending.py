"""Tests for Bakong pending feed + watcher helpers."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.payments import _require_bakong_service_api_key
from app.schemas.payment import BakongPendingIntentRead, BakongPendingListRead


def test_require_bakong_service_api_key_ok():
    with patch("app.routers.payments.get_settings") as gs:
        gs.return_value = SimpleNamespace(bakong_service_api_key="secret")
        _require_bakong_service_api_key("secret")


def test_require_bakong_service_api_key_rejects():
    from fastapi import HTTPException

    with patch("app.routers.payments.get_settings") as gs:
        gs.return_value = SimpleNamespace(bakong_service_api_key="secret")
        with pytest.raises(HTTPException) as exc:
            _require_bakong_service_api_key("wrong")
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_list_pending_bakong_payments():
    from starlette.requests import Request

    from app.routers.payments import list_pending_bakong_payments

    intent = SimpleNamespace(
        intent_id="bkg-1",
        bakong_md5="abc",
        bakong_prev_md5=None,
        created_at=datetime.now(timezone.utc),
        bakong_qr_created_at=None,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [intent]
    db = AsyncMock()
    db.execute.return_value = result
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/payments/bakong/pending",
        "raw_path": b"/payments/bakong/pending",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    request = Request(scope)

    with patch("app.routers.payments.get_settings") as gs:
        gs.return_value = SimpleNamespace(
            bakong_service_api_key="secret",
            bakong_pending_window_minutes=45,
            bakong_pending_limit=20,
        )
        out = await list_pending_bakong_payments(
            request=request,
            db=db,
            x_api_key="secret",
        )

    assert isinstance(out, BakongPendingListRead)
    assert out.items == [
        BakongPendingIntentRead(
            intent_id="bkg-1",
            md5="abc",
            prev_md5=None,
            created_at=intent.created_at,
            qr_created_at=None,
        )
    ]
