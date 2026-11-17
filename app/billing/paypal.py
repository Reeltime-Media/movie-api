"""PayPal Orders v2 client (redirect checkout) — create, capture, webhook verify.

Flow: create an order (we get an approval link) -> buyer approves on paypal.com ->
buyer lands on our return page -> we capture -> fulfill. A webhook (CHECKOUT.ORDER.APPROVED
/ PAYMENT.CAPTURE.COMPLETED) repeats the capture/fulfil so a buyer who closes the tab
after approving is still unlocked. Every call that moves money carries a stable
``PayPal-Request-Id`` so a retry can never charge twice.

Secrets (client id/secret, webhook id) come from Settings only and are never logged.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_CURRENCY = "USD"
_CLIENT_TIMEOUT_SECONDS = 20
# Refresh the OAuth token this long before PayPal says it expires.
_TOKEN_SAFETY_SECONDS = 120

_client: httpx.AsyncClient | None = None
_token: str | None = None
_token_expires_at: float = 0.0
_token_lock = asyncio.Lock()


class PaypalNotConfiguredError(RuntimeError):
    """PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set."""


class PaypalApiError(RuntimeError):
    """PayPal answered with an error. ``issue`` is PayPal's machine-readable code."""

    def __init__(self, status_code: int, issue: str, message: str) -> None:
        super().__init__(f"PayPal {status_code} {issue}: {message}")
        self.status_code = status_code
        self.issue = issue
        self.message = message


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=_CLIENT_TIMEOUT_SECONDS)
    return _client


def set_client_for_tests(client: httpx.AsyncClient | None) -> None:
    """Swap the HTTP client (tests inject an httpx.MockTransport) and drop the token."""
    global _client, _token, _token_expires_at
    _client = client
    _token = None
    _token_expires_at = 0.0


async def close_http_client() -> None:
    global _client, _token, _token_expires_at
    if _client is not None:
        await _client.aclose()
    _client = None
    _token = None
    _token_expires_at = 0.0


def format_usd(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01'))}"


def _api_error(response: httpx.Response) -> PaypalApiError:
    issue, message = "UNKNOWN", f"HTTP {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        details = body.get("details")
        if isinstance(details, list) and details and isinstance(details[0], dict):
            issue = str(details[0].get("issue") or body.get("name") or issue)
            message = str(details[0].get("description") or body.get("message") or message)
        else:
            issue = str(body.get("name") or body.get("error") or issue)
            message = str(body.get("message") or body.get("error_description") or message)
    return PaypalApiError(response.status_code, issue, message)


async def _access_token() -> str:
    global _token, _token_expires_at
    settings = get_settings()
    if not settings.paypal_enabled:
        raise PaypalNotConfiguredError("PayPal is not configured")

    now = time.monotonic()
    if _token and now < _token_expires_at:
        return _token

    async with _token_lock:
        now = time.monotonic()
        if _token and now < _token_expires_at:
            return _token
        basic = base64.b64encode(
            f"{settings.paypal_client_id.strip()}:{settings.paypal_client_secret.strip()}".encode()
        ).decode()
        response = await _get_client().post(
            f"{settings.paypal_api_base}/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            content="grant_type=client_credentials",
        )
        if response.status_code != 200:
            raise _api_error(response)
        data = response.json()
        _token = str(data["access_token"])
        _token_expires_at = now + max(60, int(data.get("expires_in", 300)) - _TOKEN_SAFETY_SECONDS)
        return _token


async def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    token = await _access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    if request_id:
        headers["PayPal-Request-Id"] = request_id
    response = await _get_client().request(
        method,
        f"{settings.paypal_api_base}{path}",
        headers=headers,
        json=json_body,
    )
    if response.status_code >= 400:
        raise _api_error(response)
    return response.json() if response.content else {}


def return_base_url(origin: str | None = None) -> str:
    """Public web origin PayPal sends the buyer back to (no trailing slash).

    The web client passes the origin it is running on so the buyer returns to the SAME
    origin (the login token lives in that origin's storage). It is only honoured when it
    is on the CORS allow-list, so a crafted request cannot point PayPal at another site.
    """
    settings = get_settings()
    requested = (origin or "").strip().rstrip("/")
    if requested and requested in {o.rstrip("/") for o in settings.cors_origin_list}:
        return requested
    explicit = settings.paypal_return_base_url.strip()
    if explicit:
        return explicit.rstrip("/")
    public = settings.app_public_url.split(",")[0].strip()
    if public:
        return public.rstrip("/")
    return settings.cors_origin_list[0].rstrip("/")


def safe_return_path(path: str | None) -> str | None:
    """Only same-site relative paths may be carried through PayPal and back.

    Rejects absolute / protocol-relative URLs and control characters so the return page
    can never be turned into an open redirect.
    """
    if not path:
        return None
    value = path.strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return None
    if len(value) > 300 or any(ord(ch) < 32 for ch in value):
        return None
    return value


def build_return_urls(
    intent_id: str,
    return_path: str | None,
    client: str,
    origin: str | None = None,
) -> tuple[str, str]:
    """(return_url, cancel_url) on the web origin; the return page does the capture."""
    base = f"{return_base_url(origin)}/pay/paypal/return"
    params: dict[str, str] = {"intent": intent_id, "client": client}
    next_path = safe_return_path(return_path)
    if next_path:
        params["next"] = next_path
    query = urlencode(params, quote_via=quote)
    return f"{base}?{query}", f"{base}?{query}&cancelled=1"


# PayPal's page for buyers without a PayPal account: card number first ("guest checkout").
# Whether PayPal shows it still depends on the merchant account and the buyer's country.
CARD_LANDING_PAGE = "GUEST_CHECKOUT"


def order_payload(
    *,
    intent_id: str,
    order_id: str,
    amount_usd: Decimal,
    description: str,
    return_url: str,
    cancel_url: str,
    landing_page: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                # custom_id comes back on every capture/webhook: it is how we bind a
                # PayPal payment to OUR intent without trusting the buyer's browser.
                "reference_id": intent_id,
                "custom_id": intent_id,
                "invoice_id": order_id,
                "description": description[:127],
                "amount": {"currency_code": _CURRENCY, "value": format_usd(amount_usd)},
            }
        ],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "brand_name": "REELTIME",
                    "shipping_preference": "NO_SHIPPING",
                    "user_action": "PAY_NOW",
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                }
            }
        },
    }
    if landing_page:
        payload["payment_source"]["paypal"]["experience_context"]["landing_page"] = landing_page
    return payload


def approve_url(order: dict[str, Any]) -> str | None:
    for link in order.get("links", []):
        if link.get("rel") in ("payer-action", "approve") and link.get("href"):
            return str(link["href"])
    return None


async def create_order(
    *,
    intent_id: str,
    order_id: str,
    amount_usd: Decimal,
    description: str,
    return_url: str,
    cancel_url: str,
    card_first: bool = False,
) -> dict[str, Any]:
    """Create the PayPal order. ``card_first`` asks PayPal to open on its card form.

    That hint is optional: if PayPal rejects it (unknown value, unsupported account) the
    order is created again without it, so the buyer still gets the normal PayPal page
    and never an error because of a nicety.
    """
    common = {
        "intent_id": intent_id,
        "order_id": order_id,
        "amount_usd": amount_usd,
        "description": description,
        "return_url": return_url,
        "cancel_url": cancel_url,
    }
    if card_first:
        try:
            return await _request(
                "POST",
                "/v2/checkout/orders",
                json_body=order_payload(**common, landing_page=CARD_LANDING_PAGE),
                request_id=f"create-{intent_id}-card",
            )
        except PaypalApiError as exc:
            if exc.status_code not in (400, 422):
                raise
            logger.warning(
                "PayPal refused the card-first hint (%s); creating a normal order", exc.issue
            )
    return await _request(
        "POST",
        "/v2/checkout/orders",
        json_body=order_payload(**common),
        # Same intent => same PayPal order if this call is retried.
        request_id=f"create-{intent_id}",
    )


async def capture_order(paypal_order_id: str, *, intent_id: str) -> dict[str, Any]:
    return await _request(
        "POST",
        f"/v2/checkout/orders/{quote(paypal_order_id, safe='')}/capture",
        json_body={},
        request_id=f"capture-{intent_id}",
    )


async def get_order(paypal_order_id: str) -> dict[str, Any]:
    return await _request("GET", f"/v2/checkout/orders/{quote(paypal_order_id, safe='')}")


def first_capture(order: dict[str, Any]) -> dict[str, Any] | None:
    for unit in order.get("purchase_units", []):
        captures = (unit.get("payments") or {}).get("captures") or []
        if captures:
            return captures[0]
    return None


def capture_matches(capture: dict[str, Any], *, intent_id: str, amount_usd: Decimal) -> bool:
    """True only when the captured money is exactly what this intent asked for."""
    amount = capture.get("amount") or {}
    try:
        paid = Decimal(str(amount.get("value")))
    except Exception:  # noqa: BLE001 - any malformed value means "does not match"
        return False
    return (
        amount.get("currency_code") == _CURRENCY
        and paid == amount_usd.quantize(Decimal("0.01"))
        and capture.get("custom_id") in (None, intent_id)
    )


async def verify_webhook_signature(headers: dict[str, str], event: dict[str, Any]) -> bool:
    """Ask PayPal whether this webhook really came from PayPal for OUR webhook id."""
    settings = get_settings()
    webhook_id = settings.paypal_webhook_id.strip()
    if not webhook_id or not settings.paypal_enabled:
        return False
    needed = {
        "auth_algo": headers.get("paypal-auth-algo"),
        "cert_url": headers.get("paypal-cert-url"),
        "transmission_id": headers.get("paypal-transmission-id"),
        "transmission_sig": headers.get("paypal-transmission-sig"),
        "transmission_time": headers.get("paypal-transmission-time"),
    }
    if not all(needed.values()):
        return False
    try:
        result = await _request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            json_body={**needed, "webhook_id": webhook_id, "webhook_event": event},
        )
    except (PaypalApiError, httpx.HTTPError):
        logger.warning("PayPal webhook signature check could not be completed", exc_info=True)
        return False
    return result.get("verification_status") == "SUCCESS"
