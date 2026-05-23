from typing import Annotated

from fastapi import APIRouter, Form

from app.dependencies import DBSession
from app.schemas.user import GoogleAuthRequest, TokenResponse, UserCreate, UserRead, user_to_read
from app.services.auth import authenticate_google, authenticate_user, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
async def register(data: UserCreate, db: DBSession):
    user = await register_user(db, data)
    return user_to_read(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    db: DBSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    _, token = await authenticate_user(db, email, password)
    return TokenResponse(access_token=token)


@router.post("/google", response_model=TokenResponse)
async def login_google(data: GoogleAuthRequest, db: DBSession):
    _, token = await authenticate_google(db, data.id_token)
    return TokenResponse(access_token=token)
