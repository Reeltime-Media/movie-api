"""Security header middleware."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.middleware.security import security_headers_middleware


def _request(*, scheme: str = "https", forwarded_proto: str | None = None) -> Request:
    headers = []
    if forwarded_proto:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": scheme,
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 443),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_security_headers_include_csp_and_hsts_on_https():
    async def call_next(_request):
        return Response("ok")

    with patch(
        "app.middleware.security.get_settings",
        return_value=SimpleNamespace(debug=False),
    ):
        response = await security_headers_middleware(_request(scheme="https"), call_next)

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert "max-age=31536000" in response.headers["Strict-Transport-Security"]


@pytest.mark.asyncio
async def test_hsts_skipped_for_local_http_debug():
    async def call_next(_request):
        return Response("ok")

    with patch(
        "app.middleware.security.get_settings",
        return_value=SimpleNamespace(debug=True),
    ):
        response = await security_headers_middleware(_request(scheme="http"), call_next)

    assert "Strict-Transport-Security" not in response.headers
    assert response.headers["Content-Security-Policy"]
