"""R2 object key layout — assets grouped by human-readable slug (from title).

Movies:
  movies/{slug}/source.mp4
  movies/{slug}/poster.{ext}
  movies/{slug}/hls/master.m3u8 (+ segments)

Series:
  series/{series_slug}/poster.{ext}
  series/{series_slug}/episodes/{episode_slug}/source.mp4
  series/{series_slug}/episodes/{episode_slug}/poster.{ext}
  series/{series_slug}/episodes/{episode_slug}/hls/master.m3u8

Legacy keys (raw/, posters/, hls/{uuid}/) remain supported by the transcoder.
"""

from __future__ import annotations

import re
import uuid
from typing import Final

MOVIES_PREFIX: Final = "movies"
SERIES_PREFIX: Final = "series"
PROMOTIONS_PREFIX: Final = "promotions"

_POSTER_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def poster_extension(content_type: str) -> str:
    return _POSTER_EXT.get(content_type, "jpg")


# ── Movies ────────────────────────────────────────────────────────────────────


def movie_dir(slug: str) -> str:
    return f"{MOVIES_PREFIX}/{slug}"


def movie_source_key(slug: str) -> str:
    return f"{movie_dir(slug)}/source.mp4"


def movie_poster_key(slug: str, content_type: str) -> str:
    return f"{movie_dir(slug)}/poster.{poster_extension(content_type)}"


def movie_hls_prefix(slug: str) -> str:
    return f"{movie_dir(slug)}/hls"


def movie_hls_master_key(slug: str) -> str:
    return f"{movie_hls_prefix(slug)}/master.m3u8"


def is_movie_asset_key(slug: str, key: str) -> bool:
    return key.startswith(f"{movie_dir(slug)}/")


# ── Series ────────────────────────────────────────────────────────────────────


def series_dir(series_slug: str) -> str:
    return f"{SERIES_PREFIX}/{series_slug}"


def series_poster_key(series_slug: str, content_type: str) -> str:
    return f"{series_dir(series_slug)}/poster.{poster_extension(content_type)}"


def episode_dir(series_slug: str, episode_slug: str) -> str:
    return f"{series_dir(series_slug)}/episodes/{episode_slug}"


def episode_source_key(series_slug: str, episode_slug: str) -> str:
    return f"{episode_dir(series_slug, episode_slug)}/source.mp4"


def episode_poster_key(series_slug: str, episode_slug: str, content_type: str) -> str:
    return f"{episode_dir(series_slug, episode_slug)}/poster.{poster_extension(content_type)}"


def episode_hls_prefix(series_slug: str, episode_slug: str) -> str:
    return f"{episode_dir(series_slug, episode_slug)}/hls"


def episode_hls_master_key(series_slug: str, episode_slug: str) -> str:
    return f"{episode_hls_prefix(series_slug, episode_slug)}/master.m3u8"


def is_episode_asset_key(series_slug: str, episode_slug: str, key: str) -> bool:
    return key.startswith(f"{episode_dir(series_slug, episode_slug)}/")


# ── Transcode output ──────────────────────────────────────────────────────────


def hls_prefix_for_source_key(source_key: str, content_id: uuid.UUID) -> str:
    """Map a source object key to the HLS upload prefix (new layout or legacy)."""
    movie_match = re.fullmatch(r"movies/([^/]+)/source\.mp4", source_key)
    if movie_match:
        return movie_hls_prefix(movie_match.group(1))

    episode_match = re.fullmatch(
        r"series/([^/]+)/episodes/([^/]+)/source\.mp4",
        source_key,
    )
    if episode_match:
        return episode_hls_prefix(episode_match.group(1), episode_match.group(2))

    return f"hls/{content_id}"


def hls_master_key_for_source_key(source_key: str, content_id: uuid.UUID) -> str:
    return f"{hls_prefix_for_source_key(source_key, content_id)}/master.m3u8"


# ── Promotion banners ───────────────────────────────────────────────────────


def promotion_banner_image_key(banner_id: uuid.UUID, content_type: str) -> str:
    return f"{PROMOTIONS_PREFIX}/{banner_id}/image.{poster_extension(content_type)}"


def is_promotion_banner_image_key(banner_id: uuid.UUID, key: str) -> bool:
    prefix = f"{PROMOTIONS_PREFIX}/{banner_id}/"
    return key.startswith(prefix) and key.endswith((".jpg", ".jpeg", ".png", ".webp"))
