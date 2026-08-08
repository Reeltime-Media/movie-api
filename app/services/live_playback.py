"""Token-gated entry point into a live TV channel's HLS output.

Unlike VOD (playback.py), live segments are not stored in R2 — they're served
directly by the restream service's HLS origin server (FFmpeg writes segments
there directly; no RTMP hop). So instead of presigning every segment, we do a
single one-time rewrite: fetch the channel's playlist, turn every relative
URI (nested playlists, segments) into an absolute URL against the origin
server, and hand that back. From then on the player talks to the origin
server (or its CDN) directly — this API never sits in the hot path of live
segment fetching.

Only the entry fetch is gated by the channel playback token; everything the
rewritten playlist points at is a plain HTTPS URL on the origin/CDN.
"""

import time
import threading
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException, status

_FETCH_TIMEOUT_SECONDS = 10
_live_playback_client: httpx.AsyncClient | None = None

# Short TTL cache so concurrent viewers authorizing at once don't each hit
# the origin server for the same channel's entry playlist.
_PLAYLIST_CACHE_TTL = 5  # seconds — live playlists roll frequently
_playlist_cache: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()


def _get_client() -> httpx.AsyncClient:
    global _live_playback_client
    if _live_playback_client is None:
        _live_playback_client = httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS)
    return _live_playback_client


async def close_http_client() -> None:
    global _live_playback_client
    if _live_playback_client is not None:
        await _live_playback_client.aclose()
        _live_playback_client = None


def _is_uri_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


async def _fetch_playlist_text(hls_url: str) -> str:
    now = time.monotonic()
    with _cache_lock:
        cached = _playlist_cache.get(hls_url)
        if cached and cached[1] > now:
            return cached[0]

    client = _get_client()
    try:
        response = await client.get(hls_url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the live channel's stream",
        ) from exc
    text = response.text

    with _cache_lock:
        _playlist_cache[hls_url] = (text, now + _PLAYLIST_CACHE_TTL)

    return text


async def build_channel_playlist(hls_url: str) -> str:
    """Fetch the channel's playlist and rewrite every URI line to an absolute
    URL against `hls_url`, so the player can resolve everything downstream
    (nested playlists, segments) directly from the origin server."""
    text = await _fetch_playlist_text(hls_url)
    out: list[str] = []
    for line in text.splitlines():
        if _is_uri_line(line):
            out.append(urljoin(hls_url, line.strip()))
        else:
            out.append(line)
    return "\n".join(out) + "\n"
