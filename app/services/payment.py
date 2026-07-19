"""Baray payment API helpers.

BARAY DISABLED — movie/subscription checkout no longer calls this module.
Code is retained for when Baray is re-enabled.
"""

import base64
import json
from decimal import Decimal

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import HTTPException, status

from app.config import get_settings

settings = get_settings()

_BLOCK_SIZE_BITS = 128
_CURRENCY = "USD"
_CLIENT_TIMEOUT_SECONDS = 15
_baray_client: httpx.AsyncClient | None = None


class BarayCredentialsError(RuntimeError):
    pass


def _get_baray_client() -> httpx.AsyncClient:
    global _baray_client
    if _baray_client is None:
        _baray_client = httpx.AsyncClient(timeout=_CLIENT_TIMEOUT_SECONDS)
    return _baray_client


async def close_http_client() -> None:
    global _baray_client
    if _baray_client is not None:
        await _baray_client.aclose()
        _baray_client = None


def _credential_pair() -> tuple[bytes, bytes]:
    if not settings.baray_api_key or not settings.baray_sk or not settings.baray_iv:
        raise BarayCredentialsError("Baray API credentials are not configured")

    try:
        key = base64.b64decode(settings.baray_sk)
        iv = base64.b64decode(settings.baray_iv)
    except ValueError as exc:
        raise BarayCredentialsError("Baray encryption credentials are invalid") from exc

    if len(key) != 32 or len(iv) != 16:
        raise BarayCredentialsError("Baray sk must be 32 bytes and iv must be 16 bytes")

    return key, iv


def _encrypt_payload(payload: dict) -> str:
    key, iv = _credential_pair()
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    padder = padding.PKCS7(_BLOCK_SIZE_BITS).padder()
    padded = padder.update(plaintext) + padder.finalize()

    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("utf-8")


def decrypt_order_id(encrypted_order_id: str) -> str:
    key, iv = _credential_pair()
    try:
        encrypted = base64.b64decode(encrypted_order_id)
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(encrypted) + decryptor.finalize()
        unpadder = padding.PKCS7(_BLOCK_SIZE_BITS).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid Baray encrypted_order_id") from exc


def checkout_url(intent_id: str) -> str:
    return f"{settings.baray_checkout_base_url.rstrip('/')}/{intent_id}"


def format_usd(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01'))}"


async def create_intent(
    *,
    amount_usd: Decimal,
    order_id: str,
    tracking: dict,
    order_details: dict | None = None,
    custom_success_url: str | None = None,
) -> dict:
    payload = {
        "amount": format_usd(amount_usd),
        "currency": _CURRENCY,
        "order_id": order_id,
        "tracking": tracking,
    }
    if order_details:
        payload["order_details"] = order_details
    if custom_success_url:
        payload["custom_success_url"] = custom_success_url
    if settings.api_public_url:
        payload["callback_url"] = f"{settings.api_public_url.rstrip('/')}/webhooks/baray"

    try:
        encrypted = _encrypt_payload(payload)
    except BarayCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    try:
        client = _get_baray_client()
        response = await client.post(
            f"{settings.baray_base_url.rstrip('/')}/pay",
            headers={
                "Content-Type": "application/json",
                "x-api-key": settings.baray_api_key,
            },
            json={"data": encrypted},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = "Baray rejected the payment intent"
        try:
            body = exc.response.json()
            if isinstance(body, dict) and isinstance(body.get("error"), str):
                detail = body["error"]
        except ValueError:
            pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Baray payment API",
        ) from exc

    data = response.json()
    if not isinstance(data, dict) or not data.get("_id"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baray returned an invalid payment intent response",
        )
    return data

