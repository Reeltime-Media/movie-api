"""Tests for Bakong pending feed + watcher helpers (pending feed disabled)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routers.payments import _require_bakong_service_api_key


def test_require_bakong_service_api_key_ok():
    with patch("app.routers.payments.get_settings") as gs:
        gs.return_value = SimpleNamespace(bakong_service_api_key="secret")
        _require_bakong_service_api_key("secret")


def test_require_bakong_service_api_key_rejects():
    with patch("app.routers.payments.get_settings") as gs:
        gs.return_value = SimpleNamespace(bakong_service_api_key="secret")
        with pytest.raises(HTTPException) as exc:
            _require_bakong_service_api_key("wrong")
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_list_pending_bakong_payments_disabled():
    from starlette.requests import Request

    from app.routers.payments import list_pending_bakong_payments

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
    with pytest.raises(HTTPException) as exc:
        await list_pending_bakong_payments(
            request=request,
            db=AsyncMock(),
            x_api_key="secret",
        )
    assert exc.value.status_code == 503
