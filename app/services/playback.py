"""Token-gated HLS playback.

The HLS objects (master playlist, per-rendition playlists, .ts segments) live in
a private R2 prefix and are never served directly. Instead:

  * The master playlist is rewritten so each rendition reference points back at
    the variant endpoint, carrying the caller's playback token.
  * Each rendition playlist is rewritten so every segment reference becomes a
    short-lived presigned R2 URL.

Segments are therefore fetched straight from R2 via expiring signatures (no app
round-trip per segment), while the playlists stay gated behind the token.
"""

import asyncio
import posixpath

from app.config import get_settings
from app.services import storage

settings = get_settings()


def _is_uri_line(line: str) -> bool:
    """A playlist line that references another resource (not a tag/comment/blank)."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


async def _get_object_text(key: str) -> str:
    def _fetch() -> str:
        obj = storage._client().get_object(
            Bucket=settings.r2_bucket_name, Key=key
        )
        return obj["Body"].read().decode("utf-8")

    return await asyncio.to_thread(_fetch)


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
    hls_master_key: str, variant_name: str, expires_in: int
) -> str:
    """Rewrite each segment reference in a rendition playlist to a presigned URL.

    `variant_name` is validated by the caller. Segment names come from our own
    transcoder output (trusted), but are still resolved within the HLS prefix.
    """
    prefix = posixpath.dirname(hls_master_key)  # e.g. movies/<slug>/hls
    variant_key = f"{prefix}/{variant_name}"
    text = await _get_object_text(variant_key)

    out: list[str] = []
    for line in text.splitlines():
        if _is_uri_line(line):
            segment_key = f"{prefix}/{line.strip()}"
            # Presigning is a local crypto op (no network) — safe to call inline.
            out.append(
                storage.generate_presigned_download_url(segment_key, expires_in)
            )
        else:
            out.append(line)
    return "\n".join(out) + "\n"
