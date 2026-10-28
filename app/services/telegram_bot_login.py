"""Phone sign-in through the Telegram bot, with no browser page.

1. App: POST /auth/telegram/bot/start → one-time code + t.me/<bot>?start=login-<code>.
2. User taps Start → Telegram posts `/start login-<code>` to /webhooks/telegram.
   Telegram vouches for `from`, so we record who it is and ask them to Confirm.
3. User taps Confirm → callback_query from that same Telegram user → confirmed.
4. App: POST /auth/telegram/bot/poll → session token, handed out once.

The Confirm step is there because whoever starts a code receives the session:
a t.me link sent to someone else must not silently sign them in on another
person's phone, so the bot spells out what is being approved first.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.core.security import generate_reset_token, hash_reset_token
from app.models.telegram_bot_login import TelegramBotLogin
from app.services.auth import login_telegram_identity
from app.services.telegram import call_bot_api

settings = get_settings()

START_PREFIX = "login-"
CONFIRM_PREFIX = "tglogin:ok:"
CANCEL_PREFIX = "tglogin:no:"

_HINT_TEXT = "Open the REELTIME app and tap “Continue with Telegram” to sign in."
_EXPIRED_TEXT = "This sign-in request has expired. Go back to the REELTIME app and try again."


def bot_login_configured() -> bool:
    return bool(
        settings.telegram_bot_token.strip()
        and settings.telegram_bot_username.strip()
        and settings.telegram_webhook_secret.strip()
    )


def _bot_username() -> str:
    return settings.telegram_bot_username.strip().lstrip("@")


async def start_bot_login(db: AsyncSession) -> tuple[str, str, str, int]:
    """Returns (raw_code, https_url, tg_app_url, expires_in_seconds)."""
    if not bot_login_configured():
        raise UnauthorizedError("Telegram sign-in is not configured")

    raw_code, code_hash = generate_reset_token()
    minutes = settings.telegram_bot_login_expire_minutes
    db.add(
        TelegramBotLogin(
            code_hash=code_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=minutes),
        )
    )
    await db.commit()

    bot = _bot_username()
    start = f"{START_PREFIX}{raw_code}"
    return (
        raw_code,
        f"https://t.me/{bot}?start={start}",
        f"tg://resolve?domain={bot}&start={start}",
        minutes * 60,
    )


def parse_login_start(text: str | None) -> str | None:
    """`/start login-<code>` → `<code>`; anything else → None."""
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0].split("@", 1)[0] != "/start":
        return None
    payload = parts[1].strip()
    if not payload.startswith(START_PREFIX):
        return None
    return payload[len(START_PREFIX) :] or None


def _display_name(row: TelegramBotLogin) -> str:
    name = " ".join(
        part for part in (row.telegram_first_name, row.telegram_last_name) if part
    ).strip()
    if name:
        return name
    return f"@{row.telegram_username}" if row.telegram_username else "your Telegram account"


async def handle_update(db: AsyncSession, update: dict) -> None:
    """Process one Bot API update. Unrelated updates are ignored."""
    message = update.get("message")
    if isinstance(message, dict):
        await _handle_message(db, message)
        return
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        await _handle_callback(db, callback)


async def _handle_message(db: AsyncSession, message: dict) -> None:
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = chat.get("id")
    sender_id = sender.get("id")
    if chat.get("type") != "private" or sender.get("is_bot") or not isinstance(sender_id, int):
        return

    text = message.get("text")
    raw_code = parse_login_start(text)
    if raw_code is None:
        if isinstance(text, str) and text.startswith("/start"):
            await call_bot_api("sendMessage", {"chat_id": chat_id, "text": _HINT_TEXT})
        return

    result = await db.execute(
        select(TelegramBotLogin)
        .where(TelegramBotLogin.code_hash == hash_reset_token(raw_code))
        .with_for_update()
    )
    row = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if (
        row is None
        or row.expires_at < now
        or not (
            row.status == "pending"
            # Tapping Start again re-sends the prompt, but only to the same person.
            or (row.status == "started" and row.telegram_id == str(sender_id))
        )
    ):
        await db.commit()
        await call_bot_api("sendMessage", {"chat_id": chat_id, "text": _EXPIRED_TEXT})
        return

    row.status = "started"
    row.telegram_id = str(sender_id)
    row.telegram_first_name = sender.get("first_name")
    row.telegram_last_name = sender.get("last_name")
    row.telegram_username = sender.get("username")
    login_id = row.id
    name = _display_name(row)
    await db.commit()

    await call_bot_api(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": (
                f"Sign in to REELTIME as {name}?\n\n"
                "Only tap Confirm if you just tapped “Continue with Telegram” in the "
                "REELTIME app on your own phone. Never confirm a link someone sent you."
            ),
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Confirm sign-in",
                            "callback_data": f"{CONFIRM_PREFIX}{login_id}",
                        },
                        {"text": "Cancel", "callback_data": f"{CANCEL_PREFIX}{login_id}"},
                    ]
                ]
            },
        },
    )


async def _handle_callback(db: AsyncSession, callback: dict) -> None:
    data = callback.get("data")
    if not isinstance(data, str):
        return
    if data.startswith(CONFIRM_PREFIX):
        approve, raw_id = True, data[len(CONFIRM_PREFIX) :]
    elif data.startswith(CANCEL_PREFIX):
        approve, raw_id = False, data[len(CANCEL_PREFIX) :]
    else:
        return
    try:
        login_id = uuid.UUID(raw_id)
    except ValueError:
        return

    sender_id = (callback.get("from") or {}).get("id")
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")

    result = await db.execute(
        select(TelegramBotLogin).where(TelegramBotLogin.id == login_id).with_for_update()
    )
    row = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if (
        row is None
        or row.status != "started"
        or row.expires_at < now
        # Only the person who tapped Start may approve it.
        or row.telegram_id != str(sender_id)
    ):
        await db.commit()
        reply = _EXPIRED_TEXT
    else:
        row.status = "confirmed" if approve else "expired"
        await db.commit()
        reply = (
            "✅ Signed in. Go back to the REELTIME app."
            if approve
            else "Sign-in cancelled. Nothing was changed."
        )

    await call_bot_api("answerCallbackQuery", {"callback_query_id": callback.get("id")})
    if chat_id is not None and message_id is not None:
        await call_bot_api(
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": reply},
        )


async def poll_bot_login(
    db: AsyncSession,
    raw_code: str,
    user_agent: str | None = None,
    guest_id: str | None = None,
) -> dict:
    """Called by the app. A confirmed code is consumed on the first poll."""
    result = await db.execute(
        select(TelegramBotLogin)
        .where(TelegramBotLogin.code_hash == hash_reset_token(raw_code))
        .with_for_update()
    )
    row = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.expires_at < now or row.status in ("used", "expired"):
        raise NotFoundError("This Telegram sign-in has expired.")
    if row.status != "confirmed" or not row.telegram_id:
        await db.commit()
        return {"status": row.status}

    row.status = "used"
    _, token = await login_telegram_identity(
        db,
        telegram_id=row.telegram_id,
        first_name=row.telegram_first_name,
        last_name=row.telegram_last_name,
        username=row.telegram_username,
        user_agent=user_agent,
        guest_id=guest_id,
    )
    return {"status": "confirmed", "access_token": token}
