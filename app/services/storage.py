"""Cloudflare R2 storage service (S3-compatible).

Presigned URL generation is a local cryptographic operation — no network call.
For operations that do hit the network (delete_object, multipart calls), run inside
a thread pool executor if called from async routes:
    await asyncio.get_event_loop().run_in_executor(None, fn, *args)

Multipart upload flow for large video files (movies 2-3h, episodes 45min-1h):
  1. create_multipart_upload(key)           → upload_id
  2. generate_presigned_part_url(key, ...)  → presigned PUT URL per chunk
     Client uploads each chunk directly to R2 (API server never sees video bytes)
  3. complete_multipart_upload(key, ...)    → finalizes the upload
  4. abort_multipart_upload(key, ...)       → cleanup on failure
"""

import boto3
from botocore.config import Config

from app.config import get_settings

settings = get_settings()

# Recommended chunk size for multipart uploads: 50 MB.
# A 2h movie at 5 Mbps ≈ 4.5 GB → ~92 parts. Max R2 parts = 10,000.
MULTIPART_PART_SIZE = 50 * 1024 * 1024  # 50 MB in bytes


def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


# ── Simple object operations ───────────────────────────────────────────────────

def upload_fileobj(file_obj, key: str, content_type: str = "application/octet-stream") -> None:
    _client().upload_fileobj(
        file_obj,
        settings.r2_bucket_name,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def generate_presigned_upload_url(
    key: str,
    content_type: str = "application/octet-stream",
    expires_in: int = 43200,  # 12 hours — enough for slow poster uploads
) -> str:
    return _client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.r2_bucket_name,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def generate_presigned_download_url(key: str, expires_in: int = 3600) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": key},
        ExpiresIn=expires_in,
    )


def object_exists(key: str) -> bool:
    try:
        _client().head_object(Bucket=settings.r2_bucket_name, Key=key)
    except Exception:
        return False
    return True


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=settings.r2_bucket_name, Key=key)


def public_url(key: str) -> str:
    """Return the CDN public URL for a key (no signing required for public buckets)."""
    return f"{settings.r2_public_url.rstrip('/')}/{key}"


# ── Multipart upload (for large video files) ───────────────────────────────────

def create_multipart_upload(key: str, content_type: str = "video/mp4") -> str:
    """Initiate a multipart upload and return the upload_id."""
    resp = _client().create_multipart_upload(
        Bucket=settings.r2_bucket_name,
        Key=key,
        ContentType=content_type,
    )
    return resp["UploadId"]


def generate_presigned_part_url(
    key: str,
    upload_id: str,
    part_number: int,
    expires_in: int = 43200,  # 12 hours per part
) -> str:
    """Return a presigned PUT URL for one chunk. Client uploads directly to R2."""
    return _client().generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": settings.r2_bucket_name,
            "Key": key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=expires_in,
    )


def complete_multipart_upload(key: str, upload_id: str, parts: list[dict]) -> None:
    """Assemble the uploaded parts into the final object.

    parts must be [{"PartNumber": int, "ETag": str}, ...] sorted by PartNumber.
    ETags come from the response headers of each part upload.
    """
    _client().complete_multipart_upload(
        Bucket=settings.r2_bucket_name,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )


def abort_multipart_upload(key: str, upload_id: str) -> None:
    """Cancel an in-progress multipart upload and free the stored parts."""
    _client().abort_multipart_upload(
        Bucket=settings.r2_bucket_name,
        Key=key,
        UploadId=upload_id,
    )
