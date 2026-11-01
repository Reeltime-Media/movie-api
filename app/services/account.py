import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError
from app.models.comment import Comment
from app.models.comment_report import CommentReport
from app.models.comment_vote import CommentVote
from app.models.device_pairing_code import DevicePairingCode
from app.models.favorite import Favorite
from app.models.password_reset_token import PasswordResetToken
from app.models.rating import Rating
from app.models.session import Session
from app.models.tv_access_code import TvAccessCode
from app.models.user import User
from app.models.user_block import UserBlock
from app.models.watch_progress import WatchProgress

DELETED_EMAIL_DOMAIN = "deleted.reeltime.fun"

_PERSONAL_TABLES = (
    WatchProgress,
    Favorite,
    Rating,
    CommentVote,
    CommentReport,
    Session,
    TvAccessCode,
    DevicePairingCode,
    PasswordResetToken,
)


def _placeholder_email(user_id: uuid.UUID) -> str:
    return f"deleted-{user_id}@{DELETED_EMAIL_DOMAIN}"


async def delete_user_account(db: AsyncSession, user: User) -> None:
    """Remove a user's personal data, as promised on /delete-account.

    The row stays, emptied of identity, because purchases and payments must
    be kept for accounting and their foreign keys point at it. The email and
    sign-in IDs are freed, so the person can sign up again as a new account.
    """
    if user.role == "admin":
        raise ForbiddenError("Admin accounts cannot be deleted from the app")

    user_id = user.id
    # Blanked rather than removed: deleting a row would cascade to other
    # people's replies.
    await db.execute(
        update(Comment)
        .where(Comment.user_id == user_id)
        .values(body="[deleted]", deleted_at=func.coalesce(Comment.deleted_at, datetime.now(UTC)))
    )
    for model in _PERSONAL_TABLES:
        await db.execute(delete(model).where(model.user_id == user_id))
    await db.execute(
        delete(UserBlock).where(
            or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
        )
    )

    user.email = _placeholder_email(user_id)
    user.password_hash = None
    user.google_id = None
    user.telegram_id = None
    user.apple_id = None
    user.avatar_url = None
    user.full_name = None
    user.is_active = False
    await db.commit()
