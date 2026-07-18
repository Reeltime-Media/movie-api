import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import false, select

from app.core.exceptions import ConflictError, NotFoundError
from app.core.guest import get_guest_id
from app.dependencies import CurrentUser, DBSession, OptionalUser
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.schemas.content import ContentListItemRead
from app.schemas.purchase import PurchaseCreate, PurchaseRead

router = APIRouter(prefix="/purchases", tags=["purchases"])


def _identity_filter(user, guest_id: str | None):
    if user:
        return Purchase.user_id == user.id
    if guest_id:
        return Purchase.guest_id == guest_id
    return false()


@router.get("/", response_model=list[PurchaseRead])
async def list_purchases(db: DBSession, request: Request, user: OptionalUser):
    result = await db.execute(
        select(Purchase).where(_identity_filter(user, get_guest_id(request)))
    )
    return result.scalars().all()


@router.get("/movies", response_model=list[ContentListItemRead])
async def list_purchased_movies(db: DBSession, request: Request, user: OptionalUser):
    """Published movies the user has purchased (for My Library)."""
    result = await db.execute(
        select(Content)
        .join(Purchase, Purchase.content_id == Content.id)
        .where(
            _identity_filter(user, get_guest_id(request)),
            Content.type == "single",
            Content.is_published.is_(True),
        )
        .order_by(Purchase.purchased_at.desc())
    )
    return [ContentListItemRead.model_validate(row) for row in result.scalars().all()]


@router.get("/{purchase_id}", response_model=PurchaseRead)
async def get_purchase(purchase_id: uuid.UUID, db: DBSession, request: Request, user: OptionalUser):
    result = await db.execute(
        select(Purchase).where(
            Purchase.id == purchase_id,
            _identity_filter(user, get_guest_id(request)),
        )
    )
    purchase = result.scalar_one_or_none()
    if not purchase:
        raise NotFoundError("Purchase not found")
    return purchase


@router.post("/", response_model=PurchaseRead, status_code=201)
async def create_purchase(data: PurchaseCreate, db: DBSession, current_user: CurrentUser):
    intent_result = await db.execute(
        select(PaymentIntent).where(
            PaymentIntent.intent_id == data.intent_id,
            PaymentIntent.user_id == current_user.id,
            PaymentIntent.kind == "single",
            PaymentIntent.status == "succeeded",
        )
    )
    intent = intent_result.scalar_one_or_none()
    if (
        not intent
        or intent.content_id != data.content_id
        or intent.order_id != data.order_id
        or intent.amount_usd != data.amount_usd
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Purchase must match a succeeded payment intent",
        )

    existing = await db.execute(
        select(Purchase).where(Purchase.intent_id == data.intent_id)
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Intent already processed")
    purchase = Purchase(user_id=current_user.id, **data.model_dump())
    db.add(purchase)
    await db.commit()
    await db.refresh(purchase)
    return purchase
