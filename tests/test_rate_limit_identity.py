from unittest.mock import patch

from starlette.requests import Request

from app.rate_limit import _rate_limit_key


def _request(headers: list[tuple[bytes, bytes]]):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    return Request(scope)


def test_rate_limit_key_prefers_session_id():
    request = _request([(b"authorization", b"******")])
    with patch("app.core.security.decode_access_token", return_value={"sid": "sid-1"}):
        assert _rate_limit_key(request) == "sid:sid-1"


def test_rate_limit_key_falls_back_to_ip():
    request = _request([])
    assert _rate_limit_key(request) == "ip:127.0.0.1"
