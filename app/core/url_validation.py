"""Validate redirect and callback URLs against configured app origins."""

from urllib.parse import urlparse

from fastapi import HTTPException, status

from app.config import get_settings


def allowed_app_origins() -> list[str]:
    settings = get_settings()
    origins: list[str] = []
    for raw in settings.cors_origins.split(","):
        origin = raw.strip().rstrip("/")
        if origin:
            origins.append(origin)
    if settings.app_public_url:
        origins.append(settings.app_public_url.strip().rstrip("/"))
    return list(dict.fromkeys(origins))


def validate_custom_success_url(url: str) -> str:
    """Ensure Baray success redirect stays on an allowed frontend origin."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="custom_success_url must be an absolute http(s) URL",
        )
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in allowed_app_origins():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="custom_success_url origin is not allowed",
        )
    path = parsed.path or "/"
    if not path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="custom_success_url path is not allowed",
        )
    return url


def validate_checkout_url(url: str) -> str:
    """Ensure checkout redirect targets the configured Baray host."""
    settings = get_settings()
    base = settings.baray_checkout_base_url.rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid checkout URL from payment provider",
        )
    if not url.startswith(f"{base}/"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Checkout URL host is not allowed",
        )
    return url
