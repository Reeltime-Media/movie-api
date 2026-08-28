from pydantic import BaseModel


class DevicePairingStartRead(BaseModel):
    code: str
    expires_in: int


class DevicePairingConfirmBody(BaseModel):
    code: str


class DevicePairingPollRead(BaseModel):
    status: str
    access_token: str | None = None
