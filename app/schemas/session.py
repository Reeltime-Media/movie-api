from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.session import Session


def session_to_read(session: Session, *, is_current: bool) -> "SessionRead":
    return SessionRead(
        id=session.id,
        device_label=session.device_label,
        created_at=session.created_at,
        is_current=is_current,
    )


class SessionRead(BaseModel):
    id: UUID
    device_label: str
    created_at: datetime
    is_current: bool

    model_config = {"from_attributes": True}
