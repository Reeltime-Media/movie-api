"""Token-gated HLS playback.

The HLS objects (master playlist, per-rendition playlists, .ts segments) live in
a private R2 prefix and are never served directly. Instead:

  * The master playlist is rewritten so each rendition reference points back at
    the variant endpoint, carrying the caller's playback token.
  * Each rendition playlist is rewritten so every segment reference points at
    the token-gated segment endpoint (same origin as the API proxy).

Segments are proxied through the API so browsers never fetch HLS .ts files
directly from R2 (which would fail CORS on the client domain).

Raw playlist text is cached in memory for up to 60 seconds so concurrent viewers
of the same title don't each trigger an R2 GET.
"""

import asyncio
import posixpath
import time
import threading

from app.config import get_settings
from app.services import storage

settings = get_settings()

# Simple TTL cache for raw playlist text fetched from R2.
# Key = R2 object key, Value = (text, expiry_monotonic).
_PLAYLIST_CACHE_TTL = 60  # seconds
_playlist_cache: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()


def _is_uri_line(line: str) -> bool:
    """A playlist line that references another resource (not a tag/comment/blank)."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


async def _get_object_text(key: str) -> str:
    # Check cache first.
    now = time.monotonic()
    with _cache_lock:
        cached = _playlist_cache.get(key)
        if cached and cached[1] > now:
            return cached[0]

    def _fetch() -> str:
        obj = storage._client().get_object(
            Bucket=settings.r2_bucket_name, Key=key
        )
        return obj["Body"].read().decode("utf-8")

    text = await asyncio.to_thread(_fetch)

    with _cache_lock:
        _playlist_cache[key] = (text, now + _PLAYLIST_CACHE_TTL)

    return text


async def build_master_playlist(
    hls_master_key: str, content_id, playback_token: str
) -> str:
    """Rewrite each rendition reference to the token-carrying variant endpoint.

    Variant URLs are kept relative to the master so playback is independent of
    the API's host/scheme; the player resolves them against the master URL.
    """
    text = await _get_object_text(hls_master_key)
    out: list[str] = []
    for line in text.splitlines():
        if _is_uri_line(line):
            name = line.strip()
            out.append(f"v/{name}?t={playback_token}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


async def build_variant_playlist(
    hls_master_key: str, variant_name: str, playback_token: str
) -> str:
    """Rewrite each segment reference to the token-gated segment endpoint.

    URLs are relative to the variant playlist (`../s/...`) so the player
    resolves them against the API host (or `/api-proxy` on the client).
    """
    prefix = posixpath.dirname(hls_master_key)  # e.g. movies/<slug>/hls
    variant_key = f"{prefix}/{variant_name}"
    text = await _get_object_text(variant_key)

    out: list[str] = []
    for line in text.splitlines():
        if _is_uri_line(line):
            segment_name = line.strip()
            out.append(f"../s/{segment_name}?t={playback_token}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


async def get_segment_bytes(hls_master_key: str, segment_name: str) -> tuple[bytes, str]:
    """Fetch one HLS segment from R2. `segment_name` is validated by the caller."""
    prefix = posixpath.dirname(hls_master_key)
    segment_key = f"{prefix}/{segment_name}"

    def _fetch() -> tuple[bytes, str]:
        obj = storage._client().get_object(
            Bucket=settings.r2_bucket_name, Key=segment_key
        )
        body = obj["Body"].read()
        content_type = obj.get("ContentType") or "video/mp2t"
        return body, content_type

    return await asyncio.to_thread(_fetch)
