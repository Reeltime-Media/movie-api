from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.models.user import User


def user_to_read(user: User) -> "UserRead":
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        role=user.role,
        is_active=user.is_active,
        has_password=user.password_hash is not None,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    password: str | None = None


class UserRead(BaseModel):
    id: UUID
    email: str
    full_name: str | None
    avatar_url: str | None = None
    role: str
    is_active: bool
    has_password: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GoogleAuthRequest(BaseModel):
    id_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
