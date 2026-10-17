import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")
os.environ.setdefault("R2_ACCOUNT_ID", "test")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("R2_BUCKET_NAME", "test")
os.environ.setdefault("R2_PUBLIC_URL", "https://cdn.test")

import httpx
import pytest
from fastapi import HTTPException

from app.services import live_client


@pytest.fixture(autouse=True)
def _live_service(monkeypatch):
    monkeypatch.setattr(live_client, "_base_url", lambda: "http://live.test")
    live_client._live_client = None
    yield
    live_client._live_client = None


def _install_transport(handler) -> None:
    live_client._live_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_slow_start_is_reported_as_timeout_not_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    _install_transport(handler)
    with pytest.raises(HTTPException) as exc_info:
        await live_client.start_channel("cid", "http://source.example/live.m3u8")
    assert exc_info.value.status_code == 504
    assert "source stream" in exc_info.value.detail


@pytest.mark.asyncio
async def test_unreachable_live_service_is_reported_as_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _install_transport(handler)
    with pytest.raises(HTTPException) as exc_info:
        await live_client.start_channel("cid", "http://source.example/live.m3u8")
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Could not reach live TV service"


@pytest.mark.asyncio
async def test_start_waits_longer_than_the_live_service_playlist_wait():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, json={"status": "error", "hls_url": None, "error": "boom"})

    _install_transport(handler)
    result = await live_client.start_channel("cid", "http://source.example/live.m3u8")
    assert result["error"] == "boom"
    # live_manager waits up to 20s for the first playlist, plus up to 10s to stop.
    assert seen["timeout"]["read"] > 30
