import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import CurrentUser, DBSession
from app.models.payment_intent import PaymentIntent
from app.models.purchase import Purchase
from app.schemas.purchase import PurchaseCreate, PurchaseRead

router = APIRouter(prefix="/purchases", tags=["purchases"])


@router.get("/", response_model=list[PurchaseRead])
async def list_purchases(db: DBSession, current_user: CurrentUser):
    result = await db.execute(
        select(Purchase).where(Purchase.user_id == current_user.id)
    )
    return result.scalars().all()


@router.get("/{purchase_id}", response_model=PurchaseRead)
async def get_purchase(purchase_id: uuid.UUID, db: DBSession, current_user: CurrentUser):
    result = await db.execute(
        select(Purchase).where(
            Purchase.id == purchase_id,
            Purchase.user_id == current_user.id,
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
