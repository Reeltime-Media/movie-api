"""Resolve pending intents when the buyer already owns the title.

Ownership is not payment evidence. Redundant unpaid intents are marked
``superseded`` so checkout UI can close without inflating revenue.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.models.series_purchase import SeriesPurchase

# Access already granted via another receipt — not a verified payment.
STATUS_SUPERSEDED = "superseded"


async def mark_succeeded_if_already_purchased(
    db: AsyncSession,
    intent: PaymentIntent,
) -> bool:
    """Unstick QR UI when the title is already owned but this intent is still pending.

    Sets status to ``superseded`` (not ``succeeded``) so dashboards that sum
    succeeded intents do not count ownership-only transitions as revenue.
    """
    if intent.user_id is not None:
        movie_owner = Purchase.user_id == intent.user_id
        series_owner = SeriesPurchase.user_id == intent.user_id
    elif intent.guest_id:
        movie_owner = Purchase.guest_id == intent.guest_id
        series_owner = SeriesPurchase.guest_id == intent.guest_id
    else:
        return False

    if intent.kind == "series" and intent.series_id is not None:
        existing = await db.execute(
            select(SeriesPurchase.id)
            .where(SeriesPurchase.series_id == intent.series_id, series_owner)
            .limit(1)
        )
        if existing.scalar_one_or_none() is None:
            return False
        intent.status = STATUS_SUPERSEDED
        intent.resolved_at = datetime.now(UTC)
        return True

    if intent.content_id is None:
        return False
    existing = await db.execute(
        select(Purchase.id).where(Purchase.content_id == intent.content_id, movie_owner).limit(1)
    )
    if existing.scalar_one_or_none() is None:
        return False
    intent.status = STATUS_SUPERSEDED
    intent.resolved_at = datetime.now(UTC)
    return True
