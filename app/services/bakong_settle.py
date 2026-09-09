"""Bakong settle helpers.

Default mode (``bakong_nbc_settle_enabled=false``): never call NBC. Paid
detection is admin Mark paid + ``POST /payments/bakong/webhook`` only.

Optional legacy mode enables ``check_transaction_by_md5`` settle.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.payment_intent import PaymentIntent
from app.services import bakong
from app.services.bakong_check_cache import STATUS_PAID, STATUS_UNKNOWN, STATUS_UNPAID
from app.services.payment_fulfillment import fulfill_payment_intent


def nbc_settle_enabled() -> bool:
    return bool(get_settings().bakong_nbc_settle_enabled)


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
    """True if current or previous KHQR md5 is settled at Bakong (NBC mode only)."""
    if not nbc_settle_enabled():
        return False
    if not intent.bakong_md5:
        return False
    status = await bakong.probe_khqr_status(intent.bakong_md5)
    if status == STATUS_PAID:
        return True
    # Rate-limit / errors: do not burn a second NBC call on prev_md5.
    if status == STATUS_UNKNOWN:
        return False
    if (
        intent.bakong_prev_md5
        and intent.bakong_prev_md5 != intent.bakong_md5
        and await bakong.check_khqr_paid(intent.bakong_prev_md5)
    ):
        return True
    return False


async def bakong_qr_confirmed_unpaid(intent: PaymentIntent) -> bool:
    """Whether it is safe to mint a replacement QR for a stale intent.

    Without NBC: allow regen on TTL alone (prev md5 kept for late admin/webhook).
    With NBC: only when checks confirm unpaid.
    """
    if not nbc_settle_enabled():
        return True

    md5s: list[str] = []
    if intent.bakong_md5:
        md5s.append(intent.bakong_md5)
    if intent.bakong_prev_md5 and intent.bakong_prev_md5 not in md5s:
        md5s.append(intent.bakong_prev_md5)
    if not md5s:
        return True
    for md5 in md5s:
        status = await bakong.probe_khqr_status(md5)
        if status == STATUS_PAID:
            return False
        if status == STATUS_UNKNOWN:
            return False
        if status != STATUS_UNPAID:
            return False
    return True


async def settle_bakong_intent_if_paid(
    db: AsyncSession,
    intent: PaymentIntent,
) -> bool:
    """Fulfill when Bakong NBC reports paid. No-op when NBC settle is disabled."""
    if intent.status == "succeeded":
        return True
    if intent.method != "bakong" or intent.status != "pending":
        return False
    if not nbc_settle_enabled():
        return False
    if not await bakong_md5s_paid(intent):
        return False
    await fulfill_payment_intent(db, intent, bank="bakong")
    return True


async def settle_pending_movie_bakong_for_buyer(
    db: AsyncSession,
    *,
    content_id: UUID,
    user_id: UUID | None,
    guest_id: str | None,
) -> bool:
    """Legacy NBC safety net on playback authorize. Disabled in self-settle mode."""
    if not nbc_settle_enabled():
        return False
    from app.services.bakong_quota import bakong_checks_blocked

    if user_id is None and not guest_id:
        return False
    if bakong_checks_blocked():
        return False

    identity = (
        (PaymentIntent.user_id == user_id)
        if user_id is not None
        else (PaymentIntent.guest_id == guest_id)
    )
    result = await db.execute(
        select(PaymentIntent)
        .where(
            identity,
            PaymentIntent.method == "bakong",
            PaymentIntent.kind == "single",
            PaymentIntent.content_id == content_id,
            PaymentIntent.status == "pending",
            PaymentIntent.bakong_md5.is_not(None),
        )
        .order_by(PaymentIntent.created_at.desc())
        .limit(2)
    )
    settled_any = False
    for intent in result.scalars().all():
        if await settle_bakong_intent_if_paid(db, intent):
            settled_any = True
            break
    return settled_any
