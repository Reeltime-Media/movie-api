"""Baray webhook signature verification."""

import hashlib
import hmac

from fastapi import HTTPException, Request, status

from app.config import get_settings

_SIGNATURE_HEADERS = (
    "x-baray-signature",
    "x-webhook-signature",
    "x-signature",
)


def _extract_signature(request: Request) -> str | None:
    for name in _SIGNATURE_HEADERS:
        value = request.headers.get(name)
        if value:
            return value.strip()
    return None


def _normalize_signature(value: str) -> str:
    value = value.strip()
    if value.startswith("sha256="):
        return value[7:]
    return value


async def verify_baray_webhook(request: Request) -> bytes:
    """Return raw body after verifying HMAC-SHA256 when a webhook secret is configured."""
    body = await request.body()
    settings = get_settings()
    secret = settings.baray_webhook_secret.strip()
    if not secret:
        if settings.debug:
            return body
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret is not configured",
        )

    provided = _extract_signature(request)
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature",
        )

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    normalized = _normalize_signature(provided)
    if not hmac.compare_digest(expected, normalized):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )
    return body
