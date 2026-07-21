"""Ops alerts via Telegram Bot API (payment success, etc.)."""

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.user import User

settings = get_settings()
logger = logging.getLogger(__name__)

_CLIENT_TIMEOUT_SECONDS = 10
_telegram_client: httpx.AsyncClient | None = None


def _get_telegram_client() -> httpx.AsyncClient:
    global _telegram_client
    if _telegram_client is None:
        _telegram_client = httpx.AsyncClient(timeout=_CLIENT_TIMEOUT_SECONDS)
    return _telegram_client


async def close_http_client() -> None:
    global _telegram_client
    if _telegram_client is not None:
        await _telegram_client.aclose()
        _telegram_client = None


async def send_telegram_message(text: str) -> None:
    """Post to TELEGRAM_CHAT_ID. Skips when unset; never raises to callers."""
    token = settings.telegram_bot_token.strip()
    chat_id = settings.telegram_chat_id.strip()
    if not token or not chat_id:
        logger.debug("Telegram not configured — skipping ops alert")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    client = _get_telegram_client()
    try:
        res = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        res.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Failed to send Telegram ops alert")


async def notify_payment_succeeded(
    db: AsyncSession,
    intent: PaymentIntent,
    *,
    bank: str | None = None,
) -> None:
    """Build and send a payment-success alert for the team chat."""
    title = "Subscription"
    if intent.kind == "single" and intent.content_id:
        row = await db.execute(select(Content.title).where(Content.id == intent.content_id))
        title = row.scalar_one_or_none() or f"content:{intent.content_id}"

    buyer = "guest"
    if intent.user_id:
        row = await db.execute(
            select(User.email, User.full_name).where(User.id == intent.user_id)
        )
        user_row = row.one_or_none()
        if user_row:
            email, full_name = user_row
            buyer = f"{full_name} <{email}>" if full_name else email
        else:
            buyer = f"user:{intent.user_id}"
    elif intent.guest_id:
        guest = intent.guest_id
        buyer = f"guest:{guest[:8]}..." if len(guest) > 8 else f"guest:{guest}"

    method = bank or intent.method or "unknown"
    kind_label = "Movie" if intent.kind == "single" else "Subscription"
    amount = f"${intent.amount_usd:.2f}"

    text = (
        "Reeltime payment succeeded\n"
        f"- {kind_label}: {title}\n"
        f"- Amount: {amount}\n"
        f"- Method: {method}\n"
        f"- Buyer: {buyer}\n"
        f"- Order: {intent.order_id}\n"
        f"- Intent: {intent.intent_id}"
    )
    await send_telegram_message(text)
