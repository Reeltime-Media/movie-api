from fastapi import APIRouter

from app.dependencies import DBSession
from app.schemas.user import TokenResponse, UserCreate, UserLogin, UserRead
from app.services.auth import authenticate_user, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
async def register(data: UserCreate, db: DBSession):
    return await register_user(db, data)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: DBSession):
    _, token = await authenticate_user(db, data.email, data.password)
    return TokenResponse(access_token=token)
