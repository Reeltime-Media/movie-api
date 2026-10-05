"""Payment intent response helpers and Bakong QR regenerate (extracted from router)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status

from app.billing import bakong
from app.billing.payment import checkout_url
from app.billing.schemas import BakongPaymentIntentRead, PaymentIntentRead
from app.config import get_settings
from app.core.money import MIN_PAID_USD
from app.core.url_validation import validate_checkout_url
from app.models.payment_intent import PaymentIntent


def validate_payment_amount(amount: Decimal | None) -> Decimal:
    if amount is None or amount < MIN_PAID_USD:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"USD payments must be at least {MIN_PAID_USD}",
        )
    return amount


def bakong_merchant_name(intent: PaymentIntent) -> str:
    return (
        (intent.bakong_merchant_name or "").strip()
        or get_settings().bakong_merchant_name.strip()
        or "Reeltime Media"
    )


def read_payment_intent(intent: PaymentIntent) -> PaymentIntentRead:
    # Bakong intents poll in place — there's no redirect target to validate.
    url = (
        validate_checkout_url(checkout_url(intent.intent_id)) if intent.method == "baray" else None
    )
    return PaymentIntentRead(
        intent_id=intent.intent_id,
        order_id=intent.order_id,
        user_id=intent.user_id,
        method=intent.method,
        kind=intent.kind,
        content_id=intent.content_id,
        series_id=intent.series_id,
        amount_usd=intent.amount_usd,
        status=intent.status,
        checkout_url=url,
        created_at=intent.created_at,
        resolved_at=intent.resolved_at,
    )


def read_bakong_intent(intent: PaymentIntent) -> BakongPaymentIntentRead:
    return BakongPaymentIntentRead(
        intent_id=intent.intent_id,
        order_id=intent.order_id,
        qr_string=intent.bakong_qr or "",
        amount_usd=intent.amount_usd,
        status=intent.status,
        created_at=intent.created_at,
        merchant_name=bakong_merchant_name(intent),
    )


async def regenerate_bakong_qr(intent: PaymentIntent) -> None:
    """Issue a fresh KHQR on the same intent; keep previous md5 for late settles."""
    from app.billing.bakong_check_cache import reset_intent_nbc_checks

    bill_number = uuid.uuid4().hex[:20]
    qr_string, md5, merchant_name = await bakong.generate_khqr(intent.amount_usd, bill_number)
    intent.bakong_prev_md5 = intent.bakong_md5
    intent.bakong_md5 = md5
    intent.bakong_qr = qr_string
    intent.bakong_merchant_name = merchant_name or intent.bakong_merchant_name
    intent.bakong_qr_created_at = datetime.now(UTC)
    # New QR gets a fresh verification budget so the 40-check cap cannot strand regen.
    reset_intent_nbc_checks(intent.intent_id)
