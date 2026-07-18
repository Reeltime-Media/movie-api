"""Bakong KHQR (National Bank of Cambodia) — inline QR checkout.

Unlike Baray, Bakong has no webhook: we generate a KHQR string locally (pure
computation, no network — safe to call even before real credentials are set),
then actively poll `check_transaction_by_md5` ourselves until it reports paid.

QR generation/md5 hashing is delegated to the `bakong-khqr` package (the EMVCo
TLV + CRC16 encoding is easy to get subtly wrong by hand). The status check is
our own async httpx call rather than the package's `check_payment`/`get_payment`
helpers, which collapse every non-success response — including an invalid or
misconfigured token — down to a bare "UNPAID"/None. Inspecting the raw
`errorCode` ourselves means a real auth/config problem gets logged distinctly
from "the customer just hasn't paid yet".
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
_bakong_client: httpx.AsyncClient | None = None


def _get_bakong_client() -> httpx.AsyncClient:
    global _bakong_client
    if _bakong_client is None:
        _bakong_client = httpx.AsyncClient(timeout=_CLIENT_TIMEOUT_SECONDS)
    return _bakong_client


async def close_http_client() -> None:
    global _bakong_client
    if _bakong_client is not None:
        await _bakong_client.aclose()
        _bakong_client = None


def _api_base() -> str:
    token = settings.bakong_developer_token
    return "https://api.bakongrelay.com/v1" if token.startswith("rbk") else "https://api-bakong.nbc.gov.kh/v1"


def generate_khqr(amount_usd: Decimal, bill_number: str) -> tuple[str, str]:
    """Pure local computation (no network) — returns (qr_string, md5)."""
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
        # Bakong's own QR validity window (days) — we enforce our own, much
        # shorter, poll timeout client-side on top of this.
        expiration=1,
    )
    return qr, khqr.generate_md5(qr)


async def check_khqr_paid(md5: str) -> bool:
    """True once Bakong reports the transaction for this md5 as settled.
    Never raises — network/API errors are logged and treated as "not yet paid"
    so a transient Bakong outage doesn't crash the poll endpoint."""
    if not settings.bakong_developer_token:
        return False

    try:
        client = _get_bakong_client()
        response = await client.post(
            f"{_api_base()}/check_transaction_by_md5",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.bakong_developer_token}",
            },
            json={"md5": md5},
        )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Bakong check_transaction_by_md5 request failed: %s", exc)
        return False

    if body.get("responseCode") == 0:
        return True

    if body.get("errorCode") == _UNAUTHORIZED_ERROR_CODE:
        logger.error(
            "Bakong rejected our developer token as unauthorized — "
            "check BAKONG_DEVELOPER_TOKEN configuration."
        )
    return False
