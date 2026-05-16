from typing import Annotated

from fastapi import APIRouter, Form

from app.dependencies import DBSession
from app.schemas.user import TokenResponse, UserCreate, UserRead
from app.services.auth import authenticate_user, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
async def register(data: UserCreate, db: DBSession):
    return await register_user(db, data)


@router.post("/login", response_model=TokenResponse)
async def login(
    db: DBSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    _, token = await authenticate_user(db, email, password)
    return TokenResponse(access_token=token)
