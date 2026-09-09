"""Token-gated HLS playback.

The HLS objects (master playlist, per-rendition playlists, .ts segments) live in
R2. Playback stays gated at the playlist layer:

  * The master playlist is rewritten so each rendition reference points back at
    the variant endpoint, carrying the caller's playback token.
  * Each rendition playlist is rewritten so every segment reference becomes a
    CDN URL on R2_PUBLIC_URL (or a short-lived presigned URL when
    PLAYBACK_SEGMENT_MODE=presign).

Segments are therefore fetched from Cloudflare's edge (no app round-trip per
segment), while the playlists stay gated behind the token.

Raw / rewritten playlist text is cached (Redis when REDIS_URL is set, otherwise
in-process) so concurrent viewers of the same title don't each hit R2 or rerun
the rewrite loop.
"""

import asyncio
import posixpath
import time
import threading

from app.config import get_settings
from app.services import storage
from app.services.shared_cache import cache_get_bytes, cache_set_bytes

settings = get_settings()

# Simple TTL cache for raw playlist text fetched from R2.
# Key = R2 object key, Value = (text, expiry_monotonic).
_PLAYLIST_CACHE_TTL = 60  # seconds
_playlist_cache: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()

# TTL cache for fully rewritten variant playlists. A full-length movie has
# ~1200 segments; without this cache the rewrite reruns on every request.
_variant_playlist_cache: dict[str, tuple[str, float]] = {}


def _is_uri_line(line: str) -> bool:
    """A playlist line that references another resource (not a tag/comment/blank)."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


async def _get_object_text(key: str) -> str:
    # Check local cache first.
    now = time.monotonic()
    with _cache_lock:
        cached = _playlist_cache.get(key)
        if cached and cached[1] > now:
            return cached[0]

    shared_key = f"hls:raw:{key}"
    shared = await cache_get_bytes(shared_key)
    if shared is not None:
        text = shared.decode("utf-8")
        with _cache_lock:
            _playlist_cache[key] = (text, now + _PLAYLIST_CACHE_TTL)
        return text

    def _fetch() -> str:
        obj = storage._client().get_object(
            Bucket=settings.r2_bucket_name, Key=key
        )
        return obj["Body"].read().decode("utf-8")

    text = await asyncio.to_thread(_fetch)

    with _cache_lock:
        _playlist_cache[key] = (text, now + _PLAYLIST_CACHE_TTL)
    await cache_set_bytes(shared_key, text.encode("utf-8"), _PLAYLIST_CACHE_TTL)

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


def _rewrite_variant_text(text: str, prefix: str, expires_in: int) -> str:
    out: list[str] = []
    for line in text.splitlines():
        if _is_uri_line(line):
            segment_key = f"{prefix}/{line.strip()}"
            out.append(storage.generate_playback_segment_url(segment_key, expires_in))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


async def build_variant_playlist(
    hls_master_key: str, variant_name: str, expires_in: int
) -> str:
    """Rewrite each segment reference in a rendition playlist to a CDN/presigned URL.

    `variant_name` is validated by the caller. Segment names come from our own
    transcoder output (trusted), but are still resolved within the HLS prefix.
    """
    prefix = posixpath.dirname(hls_master_key)  # e.g. movies/<slug>/hls
    variant_key = f"{prefix}/{variant_name}"
    mode = (settings.playback_segment_mode or "cdn").strip().lower()
    shared_key = f"hls:variant:{mode}:{variant_key}"

    now = time.monotonic()
    with _cache_lock:
        cached = _variant_playlist_cache.get(variant_key)
        if cached and cached[1] > now:
            return cached[0]

    shared = await cache_get_bytes(shared_key)
    if shared is not None:
        body = shared.decode("utf-8")
        with _cache_lock:
            _variant_playlist_cache[variant_key] = (body, now + _PLAYLIST_CACHE_TTL)
        return body

    text = await _get_object_text(variant_key)
    # CDN rewrite is cheap string work; presign is CPU-bound crypto — both run
    # off the event loop so a cold miss cannot stall other requests.
    body = await asyncio.to_thread(_rewrite_variant_text, text, prefix, expires_in)

    ttl = min(_PLAYLIST_CACHE_TTL, expires_in)
    with _cache_lock:
        _variant_playlist_cache[variant_key] = (body, now + ttl)
    await cache_set_bytes(shared_key, body.encode("utf-8"), ttl)

    return body
