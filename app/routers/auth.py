from typing import Annotated

from fastapi import APIRouter, Form, Request, Response
from app.core.guest import clear_guest_cookie, get_guest_id
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
from app.services.device_pairing import confirm_pairing, poll_pairing, start_pairing
from app.services.session import revoke_session
from app.schemas.device_pairing import (
    DevicePairingConfirmBody,
    DevicePairingPollRead,
    DevicePairingStartRead,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
@limiter.limit("10/hour")
async def register(request: Request, response: Response, data: UserCreate, db: DBSession):
    guest_id = get_guest_id(request)
    user = await register_user(db, data, guest_id)
    if guest_id:
        clear_guest_cookie(response)
    return user_to_read(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login(
    request: Request,
    response: Response,
    db: DBSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    guest_id = get_guest_id(request)
    _, token = await authenticate_user(
        db, email, password, request.headers.get("user-agent"), guest_id
    )
    if guest_id:
        clear_guest_cookie(response)
    return TokenResponse(access_token=token)


@router.post("/google", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login_google(request: Request, response: Response, data: GoogleAuthRequest, db: DBSession):
    guest_id = get_guest_id(request)
    _, token = await authenticate_google(
        db, data.id_token, request.headers.get("user-agent"), guest_id
    )
    if guest_id:
        clear_guest_cookie(response)
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


@router.post("/device/start", response_model=DevicePairingStartRead)
@limiter.limit("30/minute")
async def start_device_pairing(request: Request, db: DBSession):
    code, expires_in = await start_pairing(db)
    return DevicePairingStartRead(code=code, expires_in=expires_in)


@router.post("/device/confirm", status_code=204)
@limiter.limit("30/minute")
async def confirm_device_pairing(
    request: Request,
    db: DBSession,
    current_user: CurrentUser,
    data: DevicePairingConfirmBody,
):
    await confirm_pairing(db, data.code, current_user, request.headers.get("user-agent"))


@router.get("/device/poll", response_model=DevicePairingPollRead)
@limiter.limit("120/minute")
async def poll_device_pairing(request: Request, db: DBSession, code: str):
    result = await poll_pairing(db, code)
    return DevicePairingPollRead(**result)
