"""Shared multipart upload orchestration for movies and episodes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException

from app.schemas.upload import MultipartPart, MultipartPartUrl
from app.services import storage


async def start_multipart_upload(
    source_key: str,
    video_content_type: str,
    file_size_bytes: int,
    *,
    poster_key: str | None = None,
    poster_content_type: str | None = None,
    banner_key: str | None = None,
    banner_content_type: str | None = None,
) -> dict[str, Any]:
    loop = asyncio.get_event_loop()
    upload_id = await loop.run_in_executor(
        None, storage.create_multipart_upload, source_key, video_content_type
    )

    poster_upload_url: str | None = None
    if poster_key and poster_content_type:
        poster_upload_url = storage.generate_presigned_upload_url(
            poster_key, poster_content_type
        )

    banner_upload_url: str | None = None
    if banner_key and banner_content_type:
        banner_upload_url = storage.generate_presigned_upload_url(
            banner_key, banner_content_type
        )

    part_count = storage.multipart_part_count(file_size_bytes)
    part_urls = storage.generate_presigned_part_urls(source_key, upload_id, part_count)

    return {
        "upload_id": upload_id,
        "part_size": storage.MULTIPART_PART_SIZE,
        "part_count": part_count,
        "part_urls": [MultipartPartUrl(**entry) for entry in part_urls],
        "poster_upload_url": poster_upload_url,
        "banner_upload_url": banner_upload_url,
    }


def presigned_part_url(source_key: str, upload_id: str, part_number: int) -> str:
    return storage.generate_presigned_part_url(source_key, upload_id, part_number)


async def complete_multipart_upload(
    source_key: str,
    upload_id: str,
    parts: list[MultipartPart],
) -> None:
    if not parts:
        raise HTTPException(status_code=422, detail="parts list is empty")

    r2_parts = sorted(
        [{"PartNumber": p.part_number, "ETag": p.etag} for p in parts],
        key=lambda x: x["PartNumber"],
    )
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, storage.complete_multipart_upload, source_key, upload_id, r2_parts
        )
    except Exception as exc:
        raise HTTPException(
            status_code=409, detail=f"Failed to complete multipart upload: {exc}"
        ) from exc


async def verify_storage_objects_exist(
    *keys: str | None,
    missing_detail: str,
) -> None:
    loop = asyncio.get_event_loop()
    for key in keys:
        if not key:
            continue
        exists = await loop.run_in_executor(None, storage.object_exists, key)
        if not exists:
            raise HTTPException(status_code=409, detail=missing_detail)


async def abort_multipart_upload(source_key: str, upload_id: str) -> None:
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, storage.abort_multipart_upload, source_key, upload_id
        )
    except Exception:
        pass
