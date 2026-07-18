"""Re-assign anonymous guest purchases to a real account on login/register."""

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase


async def claim_guest_purchases(
    db: AsyncSession, user_id: uuid.UUID, guest_id: str | None
) -> None:
    """No-op if there's no guest cookie. Doesn't dedupe against purchases the
    account already owns — a duplicate row is harmless since entitlement
    checks only need one matching purchase."""
    if not guest_id:
        return
    await db.execute(
        update(Purchase)
        .where(Purchase.guest_id == guest_id)
        .values(user_id=user_id, guest_id=None)
    )
    await db.execute(
        update(PaymentIntent)
        .where(PaymentIntent.guest_id == guest_id)
        .values(user_id=user_id, guest_id=None)
    )
