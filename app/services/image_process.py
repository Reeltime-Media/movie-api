"""Resize and compress poster/banner images stored in R2 after client upload."""

from __future__ import annotations

import asyncio
import io
import logging
import posixpath
from typing import Literal

from PIL import Image

from app.services import storage

logger = logging.getLogger(__name__)

ImageKind = Literal["poster", "banner"]

POSTER_MAX_WIDTH = 800
BANNER_MAX_WIDTH = 1920
WEBP_QUALITY = 82
# Already-small WebP files are left alone.
SKIP_IF_BYTES = 250_000

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def webp_key_for(key: str) -> str:
    base, _ext = posixpath.splitext(key)
    return f"{base}.webp"


def is_image_object_key(key: str) -> bool:
    lowered = key.lower()
    return lowered.endswith(_IMAGE_SUFFIXES)


def optimize_image_bytes(data: bytes, *, kind: ImageKind) -> bytes:
    """Resize and encode as WebP. Runs in a thread pool (CPU + Pillow)."""
    with Image.open(io.BytesIO(data)) as img:
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        max_width = POSTER_MAX_WIDTH if kind == "poster" else BANNER_MAX_WIDTH
        width, height = img.size
        if width > max_width:
            new_height = max(1, round(height * max_width / width))
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="WEBP", quality=WEBP_QUALITY, method=4)
        return out.getvalue()


def _optimize_r2_image_sync(key: str, *, kind: ImageKind) -> str:
    original = storage.get_object_bytes(key)
    if key.lower().endswith(".webp") and len(original) <= SKIP_IF_BYTES:
        return key

    optimized = optimize_image_bytes(original, kind=kind)
    target_key = webp_key_for(key)

    if target_key == key and len(optimized) >= len(original):
        return key

    storage.put_object_bytes(target_key, optimized, "image/webp")
    if target_key != key:
        storage.delete_object(key)

    logger.info(
        "Optimized %s image %s -> %s (%d KB -> %d KB)",
        kind,
        key,
        target_key,
        len(original) // 1024,
        len(optimized) // 1024,
    )
    return target_key


async def optimize_r2_image(key: str | None, *, kind: ImageKind) -> str | None:
    """Download from R2, compress, re-upload as WebP. Returns the final object key."""
    if not key or not is_image_object_key(key):
        return key

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(
            None, lambda: _optimize_r2_image_sync(key, kind=kind)
        )
    except Exception:
        logger.exception("Failed to optimize %s image at %s", kind, key)
        return key
