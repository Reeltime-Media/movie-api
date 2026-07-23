"""Bakong KHQR client for movie-api.

When BAKONG_SERVICE_URL is set, QR generation and paid-checks go to the
Cambodia-hosted `payment-bakong` service (NBC blocks non-KH egress).
Otherwise falls back to in-process Bakong calls (local/Cambodia-only).
"""

import logging
from decimal import Decimal

import httpx
from bakong_khqr import KHQR
from fastapi import HTTPException, status

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_CLIENT_TIMEOUT_SECONDS = 15
_UNAUTHORIZED_ERROR_CODE = 6
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=_CLIENT_TIMEOUT_SECONDS)
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def _service_base() -> str:
    return (settings.bakong_service_url or "").strip().rstrip("/")


def _uses_remote_service() -> bool:
    return bool(_service_base())


def _nbc_api_base() -> str:
    override = (settings.bakong_api_base_url or "").strip().rstrip("/")
    if override:
        return override
    token = settings.bakong_developer_token
    return (
        "https://api.bakongrelay.com/v1"
        if token.startswith("rbk")
        else "https://api-bakong.nbc.gov.kh/v1"
    )


def _service_headers() -> dict[str, str]:
    key = settings.bakong_service_api_key.strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BAKONG_SERVICE_API_KEY is not configured",
        )
    return {"Content-Type": "application/json", "X-API-Key": key}


async def generate_khqr(amount_usd: Decimal, bill_number: str) -> tuple[str, str, str]:
    """Returns (qr_string, md5, merchant_name)."""
    if _uses_remote_service():
        return await _remote_generate_khqr(amount_usd, bill_number)
    return _local_generate_khqr(amount_usd, bill_number)


def _local_generate_khqr(amount_usd: Decimal, bill_number: str) -> tuple[str, str, str]:
    if not settings.bakong_developer_token or not settings.bakong_account_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bakong is not configured",
        )

    khqr = KHQR(settings.bakong_developer_token)
    qr = khqr.create_qr(
        account_id=settings.bakong_account_id,
        merchant_name=settings.bakong_merchant_name,
        merchant_city=settings.bakong_merchant_city,
        amount=float(amount_usd),
        currency="USD",
        bill_number=bill_number[:25],
        static=False,
        # bakong-khqr only accepts whole days (min 1). App TTL is BAKONG_QR_TTL_MINUTES.
        expiration=1,
    )
    return qr, khqr.generate_md5(qr), settings.bakong_merchant_name


async def _remote_generate_khqr(amount_usd: Decimal, bill_number: str) -> tuple[str, str, str]:
    url = f"{_service_base()}/v1/khqr"
    try:
        response = await _get_http_client().post(
            url,
            headers=_service_headers(),
            json={"amount_usd": str(amount_usd), "bill_number": bill_number[:25]},
        )
    except httpx.HTTPError as exc:
        logger.error("payment-bakong /v1/khqr request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bakong payment service unreachable",
        ) from exc

    if response.status_code >= 400:
        logger.error(
            "payment-bakong /v1/khqr HTTP %s: %s",
            response.status_code,
            response.text[:300],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bakong payment service error",
        )

    body = response.json()
    return body["qr_string"], body["md5"], body.get("merchant_name") or settings.bakong_merchant_name


async def check_khqr_paid(md5: str) -> bool:
    """True once Bakong reports the transaction for this md5 as settled."""
    from app.services.bakong_check_cache import get_cached_md5_paid, set_cached_md5_paid

    cached = get_cached_md5_paid(md5)
    if cached is not None:
        return cached

    if _uses_remote_service():
        paid = await _remote_check_khqr_paid(md5)
    else:
        paid = await _local_check_khqr_paid(md5)

    set_cached_md5_paid(md5, paid)
    return paid


async def _remote_check_khqr_paid(md5: str) -> bool:
    url = f"{_service_base()}/v1/check"
    try:
        response = await _get_http_client().post(
            url,
            headers=_service_headers(),
            json={"md5": md5},
        )
    except httpx.HTTPError as exc:
        logger.warning("payment-bakong /v1/check request failed: %s", exc)
        return False

    if response.status_code >= 400:
        logger.warning(
            "payment-bakong /v1/check HTTP %s: %s",
            response.status_code,
            response.text[:200],
        )
        return False

    try:
        return bool(response.json().get("paid"))
    except ValueError:
        logger.warning("payment-bakong /v1/check non-JSON body")
        return False


async def _local_check_khqr_paid(md5: str) -> bool:
    if not settings.bakong_developer_token:
        return False

    url = f"{_nbc_api_base()}/check_transaction_by_md5"
    try:
        response = await _get_http_client().post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.bakong_developer_token}",
            },
            json={"md5": md5},
        )
    except httpx.HTTPError as exc:
        logger.warning("Bakong check_transaction_by_md5 request failed: %s", exc)
        return False

    content_type = (response.headers.get("content-type") or "").lower()
    if response.status_code == 403 or "text/html" in content_type:
        logger.error(
            "Bakong check blocked (HTTP %s) from this server IP — set "
            "BAKONG_SERVICE_URL to the Cambodia payment-bakong service. url=%s",
            response.status_code,
            url,
        )
        return False

    try:
        body = response.json()
    except ValueError as exc:
        logger.warning(
            "Bakong check_transaction_by_md5 non-JSON (HTTP %s): %s",
            response.status_code,
            exc,
        )
        return False

    if body.get("responseCode") == 0:
        return True

    if body.get("errorCode") == _UNAUTHORIZED_ERROR_CODE:
        logger.error(
            "Bakong rejected our developer token as unauthorized — "
            "check BAKONG_DEVELOPER_TOKEN configuration."
        )
    return False
