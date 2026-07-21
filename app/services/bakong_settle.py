"""Bakong settle helpers — check current/prev md5 and fulfill when paid."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.payment_intent import PaymentIntent
from app.services import bakong
from app.services.payment_fulfillment import fulfill_payment_intent


def qr_issued_at(intent: PaymentIntent) -> datetime | None:
    return intent.bakong_qr_created_at or intent.created_at


def qr_is_stale(intent: PaymentIntent, *, now: datetime | None = None) -> bool:
    issued = qr_issued_at(intent)
    if issued is None:
        return True
    now = now or datetime.now(timezone.utc)
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
    ttl = timedelta(minutes=get_settings().bakong_qr_ttl_minutes)
    return now - issued >= ttl


async def bakong_md5s_paid(intent: PaymentIntent) -> bool:
    """True if current or previous KHQR md5 is settled at Bakong."""
    # Check current md5 first (happy path). Only hit prev when current is unpaid.
    if intent.bakong_md5 and await bakong.check_khqr_paid(intent.bakong_md5):
        return True
    if (
        intent.bakong_prev_md5
        and intent.bakong_prev_md5 != intent.bakong_md5
        and await bakong.check_khqr_paid(intent.bakong_prev_md5)
    ):
        return True
    return False


async def settle_bakong_intent_if_paid(
    db: AsyncSession,
    intent: PaymentIntent,
) -> bool:
    """Fulfill when Bakong reports paid. Returns True if intent is succeeded after."""
    if intent.status == "succeeded":
        return True
    if intent.method != "bakong" or intent.status != "pending":
        return False
    if not await bakong_md5s_paid(intent):
        return False
    await fulfill_payment_intent(db, intent, bank="bakong")
    return True
