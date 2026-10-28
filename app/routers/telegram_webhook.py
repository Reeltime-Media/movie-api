import hmac
import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.config import get_settings
from app.dependencies import DBSession
from app.services.telegram_bot_login import handle_update

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/telegram")
async def telegram_webhook(request: Request, db: DBSession):
    """Bot API updates (registered with scripts/set_telegram_webhook.py)."""
    secret = get_settings().telegram_webhook_secret.strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram webhook is not configured",
        )
    received = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not hmac.compare_digest(received.encode(), secret.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret")

    try:
        update = await request.json()
    except ValueError:
        return {"ok": True}
    if not isinstance(update, dict):
        return {"ok": True}

    try:
        await handle_update(db, update)
    except Exception:
        # A non-2xx makes Telegram redeliver the same update over and over.
        logger.exception("Telegram update %s failed", update.get("update_id"))
        await db.rollback()
    return {"ok": True}
