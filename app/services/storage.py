"""Cloudflare R2 storage service (S3-compatible).

Presigned URL generation is a local cryptographic operation — no network call.
For operations that do hit the network (delete_object), run inside a thread pool
executor if called from async routes:
    await asyncio.get_event_loop().run_in_executor(None, delete_object, key)
"""

import boto3
from botocore.config import Config

from app.config import get_settings

settings = get_settings()


def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload_fileobj(file_obj, key: str, content_type: str = "video/mp4") -> None:
    _client().upload_fileobj(
        file_obj,
        settings.r2_bucket_name,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def generate_presigned_upload_url(
    key: str,
    content_type: str = "video/mp4",
    expires_in: int = 3600,
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
