import uuid

from fastapi import APIRouter

from app.dependencies import AdminUser, DBSession
from app.schemas.tv_access_code import (
    TvAccessCodeCreate,
    TvAccessCodeRead,
    TvAccessCodeUpdate,
)
from app.services import tv_access_codes as service

router = APIRouter()


@router.get("/tv-access-codes", response_model=list[TvAccessCodeRead])
async def list_admin_tv_access_codes(db: DBSession, _: AdminUser):
    return await service.list_tv_access_codes(db)


@router.post("/tv-access-codes", response_model=TvAccessCodeRead, status_code=201)
async def create_admin_tv_access_code(
    data: TvAccessCodeCreate,
    db: DBSession,
    _: AdminUser,
):
    return await service.create_tv_access_code(db, data)


@router.patch("/tv-access-codes/{code_id}", response_model=TvAccessCodeRead)
async def update_admin_tv_access_code(
    code_id: uuid.UUID,
    data: TvAccessCodeUpdate,
    db: DBSession,
    _: AdminUser,
):
    return await service.update_tv_access_code(db, code_id, data)


@router.delete("/tv-access-codes/{code_id}", status_code=204)
async def delete_admin_tv_access_code(
    code_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    await service.delete_tv_access_code(db, code_id)
