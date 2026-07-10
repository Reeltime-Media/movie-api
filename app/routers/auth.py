from typing import Annotated

from fastapi import APIRouter, Form, Request
from app.dependencies import CurrentSessionId, CurrentUser, DBSession
from app.rate_limit import limiter
from app.schemas.user import (
    ForgotPasswordRequest,
    GoogleAuthRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserCreate,
    UserRead,
    user_to_read,
)
from app.services.auth import (
    authenticate_google,
    authenticate_user,
    register_user,
    request_password_reset,
    reset_password,
)
from app.services.session import revoke_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
@limiter.limit("10/hour")
async def register(request: Request, data: UserCreate, db: DBSession):
    user = await register_user(db, data)
    return user_to_read(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login(
    request: Request,
    db: DBSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    _, token = await authenticate_user(db, email, password, request.headers.get("user-agent"))
    return TokenResponse(access_token=token)


@router.post("/google", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login_google(request: Request, data: GoogleAuthRequest, db: DBSession):
    _, token = await authenticate_google(
        db, data.id_token, request.headers.get("user-agent")
    )
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=204)
async def logout(db: DBSession, current_user: CurrentUser, session_id: CurrentSessionId):
    await revoke_session(db, current_user.id, session_id)


@router.post("/forgot-password", status_code=204)
@limiter.limit("5/hour")
async def forgot_password(request: Request, data: ForgotPasswordRequest, db: DBSession):
    await request_password_reset(db, data.email)


@router.post("/reset-password", status_code=204)
@limiter.limit("10/hour")
async def reset_password_endpoint(request: Request, data: ResetPasswordRequest, db: DBSession):
    await reset_password(db, data.token, data.password)
