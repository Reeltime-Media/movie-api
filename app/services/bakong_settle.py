"""Bakong settle helpers — check current/prev md5 and fulfill when paid."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.payment_intent import PaymentIntent
from app.services import bakong
from app.services.bakong_check_cache import STATUS_PAID, STATUS_UNKNOWN, STATUS_UNPAID
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
    from app.services.bakong_check_cache import STATUS_PAID, STATUS_UNKNOWN

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
    """True only when NBC confirmed current (and prev) KHQR are unpaid.

    Rate-limits / errors are inconclusive — keep the existing QR so we do not
    issue a second bill for a payment we failed to see.
    """
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
    """Fulfill when Bakong reports paid. Returns True if intent is succeeded after."""
    if intent.status == "succeeded":
        return True
    if intent.method != "bakong" or intent.status != "pending":
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
    """Settle any pending Bakong movie QR for this buyer+title.

    Safety net when the checkout tab closed or NBC checks were rate-limited
    after the customer already paid — play/authorize and reopen-checkout call
    this so a paid QR still unlocks the movie.
    """
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
