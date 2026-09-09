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


def nbc_reports_paid(body: dict | None) -> bool:
    """NBC marks a KHQR paid when responseCode is 0 (int or string)."""
    if not body:
        return False
    return body.get("responseCode") in (0, "0", "00")


async def probe_khqr_status(md5: str) -> str:
    """paid, unpaid, or unknown (rate-limit / transport — do not treat as unpaid)."""
    from app.services.bakong_check_cache import (
        STATUS_PAID,
        STATUS_UNKNOWN,
        STATUS_UNPAID,
        get_cached_md5_status,
        set_cached_md5_status,
    )
    from app.services.bakong_quota import bakong_checks_blocked, note_bakong_rate_limited

    if not md5:
        return STATUS_UNPAID
    cached = get_cached_md5_status(md5)
    if cached is not None:
        return cached

    if bakong_checks_blocked():
        set_cached_md5_status(md5, STATUS_UNKNOWN)
        return STATUS_UNKNOWN

    if _uses_remote_service():
        paid, inconclusive = await _remote_check_khqr_paid(md5)
    else:
        paid, inconclusive = await _local_check_khqr_paid(md5)

    if paid:
        status = STATUS_PAID
        from app.services.bakong_quota import clear_bakong_rate_limit

        clear_bakong_rate_limit()
    elif inconclusive:
        status = STATUS_UNKNOWN
        note_bakong_rate_limited()
    else:
        status = STATUS_UNPAID
    set_cached_md5_status(md5, status)
    return status


async def check_khqr_paid(md5: str) -> bool:
    """True once Bakong reports the transaction for this md5 as settled."""
    from app.services.bakong_check_cache import STATUS_PAID

    return await probe_khqr_status(md5) == STATUS_PAID


async def _alert_if_daily_limit(error_code: object) -> bool:
    from app.services.telegram import is_bakong_daily_limit_error, notify_bakong_daily_limit

    if not is_bakong_daily_limit_error(error_code):
        return False
    await notify_bakong_daily_limit()
    return True


async def _remote_check_khqr_paid(md5: str) -> tuple[bool, bool]:
    url = f"{_service_base()}/v1/check"
    try:
        response = await _get_http_client().post(
            url,
            headers=_service_headers(),
            json={"md5": md5},
        )
    except httpx.HTTPError as exc:
        logger.warning("payment-bakong /v1/check request failed: %s", exc)
        return False, True

    if response.status_code == 429:
        logger.warning("payment-bakong /v1/check HTTP 429 md5=%s", md5[:8])
        return False, True

    if response.status_code >= 400:
        logger.warning(
            "payment-bakong /v1/check HTTP %s: %s",
            response.status_code,
            response.text[:200],
        )
        return False, True

    try:
        body = response.json()
    except ValueError:
        logger.warning("payment-bakong /v1/check non-JSON body")
        return False, False

    paid = bool(body.get("paid")) or nbc_reports_paid(body)
    rate_limited = bool(body.get("rate_limited"))
    error_code = body.get("error_code")
    logger.info(
        "Bakong check md5=%s paid=%s rate_limited=%s response_code=%s error_code=%s",
        md5[:8],
        paid,
        rate_limited,
        body.get("response_code"),
        error_code,
    )
    if await _alert_if_daily_limit(error_code):
        return paid, True
    return paid, rate_limited


async def _local_check_khqr_paid(md5: str) -> tuple[bool, bool]:
    if not settings.bakong_developer_token:
        return False, False

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
        return False, True

    if response.status_code == 429:
        logger.warning("Bakong check rate-limited (HTTP 429) md5=%s", md5[:8])
        return False, True

    content_type = (response.headers.get("content-type") or "").lower()
    if response.status_code == 403 or "text/html" in content_type:
        logger.error(
            "Bakong check blocked (HTTP %s) from this server IP — set "
            "BAKONG_SERVICE_URL to the Cambodia payment-bakong service. url=%s",
            response.status_code,
            url,
        )
        return False, True

    try:
        body = response.json()
    except ValueError as exc:
        logger.warning(
            "Bakong check_transaction_by_md5 non-JSON (HTTP %s): %s",
            response.status_code,
            exc,
        )
        return False, False

    paid = nbc_reports_paid(body)
    logger.info(
        "Bakong check md5=%s http=%s responseCode=%s errorCode=%s paid=%s",
        md5[:8],
        response.status_code,
        body.get("responseCode"),
        body.get("errorCode"),
        paid,
    )
    if body.get("errorCode") == _UNAUTHORIZED_ERROR_CODE:
        logger.error(
            "Bakong rejected our developer token as unauthorized — "
            "check BAKONG_DEVELOPER_TOKEN configuration."
        )
    if await _alert_if_daily_limit(body.get("errorCode")):
        return paid, True
    return paid, False
