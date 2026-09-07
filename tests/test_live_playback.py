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

from app.services import live_playback

_MASTER_PLAYLIST = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1280000
720p.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=640000
480p.m3u8
"""

_MEDIA_PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXTINF:6.0,
segment1.ts
#EXTINF:6.0,
segment2.ts
"""


@pytest.fixture(autouse=True)
def _reset_client():
    live_playback._playlist_cache.clear()
    live_playback._live_playback_client = None
    yield
    live_playback._playlist_cache.clear()
    live_playback._live_playback_client = None


def _install_transport(text: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=text)

    live_playback._live_playback_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_rewrites_master_playlist_variants_to_absolute_urls():
    _install_transport(_MASTER_PLAYLIST)
    body = await live_playback.build_channel_playlist(
        "https://media.example.com/channel1/index.m3u8"
    )
    assert "https://media.example.com/channel1/720p.m3u8" in body
    assert "https://media.example.com/channel1/480p.m3u8" in body
    assert "#EXT-X-STREAM-INF" in body


@pytest.mark.asyncio
async def test_rewrites_media_playlist_segments_to_absolute_urls():
    _install_transport(_MEDIA_PLAYLIST)
    body = await live_playback.build_channel_playlist(
        "https://media.example.com/channel1/720p.m3u8"
    )
    assert "https://media.example.com/channel1/segment1.ts" in body
    assert "https://media.example.com/channel1/segment2.ts" in body


@pytest.mark.asyncio
async def test_playlist_cache_expires_after_one_second(monkeypatch):
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return httpx.Response(200, text=_MEDIA_PLAYLIST)

    live_playback._live_playback_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    clock = {"t": 100.0}
    monkeypatch.setattr(live_playback.time, "monotonic", lambda: clock["t"])

    url = "https://media.example.com/channel1/720p.m3u8"
    await live_playback.build_channel_playlist(url)
    await live_playback.build_channel_playlist(url)
    assert hits["n"] == 1

    clock["t"] += 1.1
    await live_playback.build_channel_playlist(url)
    assert hits["n"] == 2


@pytest.mark.asyncio
async def test_upstream_failure_raises_502():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    live_playback._live_playback_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    with pytest.raises(Exception) as exc_info:
        await live_playback.build_channel_playlist("https://media.example.com/down.m3u8")
    assert getattr(exc_info.value, "status_code", None) == 502
