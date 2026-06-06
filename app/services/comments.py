import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.comment import Comment
from app.models.comment_report import CommentReport
from app.models.comment_vote import CommentVote
from app.models.content import Content
from app.models.user import User
from app.schemas.comment import CommentAuthorRead, CommentRead, CommentThreadRead

MAX_REPLY_DEPTH = 8


def author_display_name(user: User) -> str:
    if user.full_name and user.full_name.strip():
        return user.full_name.strip()
    local = user.email.split("@", 1)[0]
    return local or "User"


def to_comment_read(
    comment: Comment,
    author: User,
    *,
    score: int = 0,
    user_vote: int | None = None,
    user_reported: bool = False,
) -> CommentRead:
    return CommentRead(
        id=comment.id,
        content_id=comment.content_id,
        parent_id=comment.parent_id,
        body=comment.body,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        author=CommentAuthorRead(
            id=author.id,
            display_name=author_display_name(author),
        ),
        score=score,
        user_vote=user_vote,
        user_reported=user_reported,
    )


def build_comment_threads(
    rows: list[tuple[Comment, User]],
    *,
    scores: dict[uuid.UUID, int],
    user_votes: dict[uuid.UUID, int],
    user_reported: set[uuid.UUID],
    root_ids: list[uuid.UUID],
) -> list[CommentThreadRead]:
    by_id: dict[uuid.UUID, CommentThreadRead] = {}
    children: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)

    for comment, author in rows:
        node = CommentThreadRead(
            **to_comment_read(
                comment,
                author,
                score=scores.get(comment.id, 0),
                user_vote=user_votes.get(comment.id),
                user_reported=comment.id in user_reported,
            ).model_dump(),
            replies=[],
        )
        by_id[comment.id] = node
        children[comment.parent_id].append(comment.id)

    for parent_id, child_ids in children.items():
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if not parent:
            continue
        parent.replies = [
            by_id[cid] for cid in sorted(child_ids, key=lambda cid: by_id[cid].created_at)
        ]

    return [by_id[rid] for rid in root_ids if rid in by_id]


async def get_comment_or_404(db: AsyncSession, comment_id: uuid.UUID) -> Comment:
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment or comment.deleted_at is not None:
        raise NotFoundError("Comment not found")
    return comment


async def get_movie_content_or_404(db: AsyncSession, content_id: uuid.UUID) -> Content:
    result = await db.execute(select(Content).where(Content.id == content_id))
    content = result.scalar_one_or_none()
    if not content or content.type != "single":
        raise NotFoundError("Movie not found")
    return content


async def ensure_commentable_movie(
    db: AsyncSession, content_id: uuid.UUID, *, allow_unpublished: bool = False
) -> Content:
    content = await get_movie_content_or_404(db, content_id)
    if not allow_unpublished and content.status != "published":
        raise NotFoundError("Movie not found")
    return content


async def _comment_depth(db: AsyncSession, comment: Comment) -> int:
    depth = 0
    current = comment
    while current.parent_id is not None:
        depth += 1
        if depth > MAX_REPLY_DEPTH:
            break
        result = await db.execute(select(Comment).where(Comment.id == current.parent_id))
        parent = result.scalar_one_or_none()
        if not parent or parent.deleted_at is not None:
            raise NotFoundError("Parent comment not found")
        current = parent
    return depth


async def validate_parent_comment(
    db: AsyncSession, *, content_id: uuid.UUID, parent_id: uuid.UUID | None
) -> None:
    if parent_id is None:
        return

    parent = await get_comment_or_404(db, parent_id)
    if parent.content_id != content_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parent comment belongs to a different movie",
        )

    depth = await _comment_depth(db, parent)
    if depth >= MAX_REPLY_DEPTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum reply depth reached",
        )


async def load_vote_and_report_maps(
    db: AsyncSession,
    comment_ids: list[uuid.UUID],
    current_user_id: uuid.UUID | None,
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int], set[uuid.UUID]]:
    if not comment_ids:
        return {}, {}, set()

    score_result = await db.execute(
        select(CommentVote.comment_id, func.coalesce(func.sum(CommentVote.value), 0))
        .where(CommentVote.comment_id.in_(comment_ids))
        .group_by(CommentVote.comment_id)
    )
    scores = {row.comment_id: int(row[1]) for row in score_result.all()}

    if current_user_id is None:
        return scores, {}, set()

    vote_result = await db.execute(
        select(CommentVote).where(
            CommentVote.user_id == current_user_id,
            CommentVote.comment_id.in_(comment_ids),
        )
    )
    user_votes = {v.comment_id: v.value for v in vote_result.scalars().all()}

    report_result = await db.execute(
        select(CommentReport.comment_id).where(
            CommentReport.user_id == current_user_id,
            CommentReport.comment_id.in_(comment_ids),
        )
    )
    user_reported = set(report_result.scalars().all())

    return scores, user_votes, user_reported


async def fetch_thread_rows_for_roots(
    db: AsyncSession, content_id: uuid.UUID, root_ids: list[uuid.UUID]
) -> list[tuple[Comment, User]]:
    if not root_ids:
        return []

    all_ids = set(root_ids)
    frontier = list(root_ids)
    while frontier:
        child_result = await db.execute(
            select(Comment.id).where(
                Comment.parent_id.in_(frontier),
                Comment.deleted_at.is_(None),
            )
        )
        child_ids = [row[0] for row in child_result.all()]
        frontier = [cid for cid in child_ids if cid not in all_ids]
        all_ids.update(frontier)

    result = await db.execute(
        select(Comment, User)
        .join(User, Comment.user_id == User.id)
        .where(
            Comment.id.in_(all_ids),
            Comment.deleted_at.is_(None),
        )
    )
    return list(result.all())


async def list_comment_threads(
    db: AsyncSession,
    *,
    content_id: uuid.UUID,
    current_user_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> tuple[list[CommentThreadRead], int]:
    roots_stmt = (
        select(Comment.id)
        .where(
            Comment.content_id == content_id,
            Comment.parent_id.is_(None),
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at.desc())
    )
    count_stmt = select(func.count()).select_from(roots_stmt.subquery())
    total = await db.scalar(count_stmt) or 0

    root_result = await db.execute(
        roots_stmt.offset((page - 1) * page_size).limit(page_size)
    )
    root_ids = [row[0] for row in root_result.all()]

    rows = await fetch_thread_rows_for_roots(db, content_id, root_ids)
    comment_ids = [comment.id for comment, _ in rows]
    scores, user_votes, user_reported = await load_vote_and_report_maps(
        db, comment_ids, current_user_id
    )
    return (
        build_comment_threads(
            rows,
            scores=scores,
            user_votes=user_votes,
            user_reported=user_reported,
            root_ids=root_ids,
        ),
        total,
    )


async def soft_delete_comment(db: AsyncSession, comment: Comment) -> None:
    comment.deleted_at = datetime.now(timezone.utc)
    await db.commit()


async def update_comment_body(db: AsyncSession, comment: Comment, body: str) -> Comment:
    comment.body = body.strip()
    comment.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(comment)
    return comment


async def set_comment_vote(
    db: AsyncSession,
    *,
    comment: Comment,
    user_id: uuid.UUID,
    value: int,
) -> tuple[int, int | None]:
    if value not in (-1, 0, 1):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid vote")

    result = await db.execute(
        select(CommentVote).where(
            CommentVote.user_id == user_id,
            CommentVote.comment_id == comment.id,
        )
    )
    existing = result.scalar_one_or_none()

    if value == 0:
        if existing:
            await db.delete(existing)
    elif existing:
        existing.value = value
    else:
        db.add(CommentVote(user_id=user_id, comment_id=comment.id, value=value))

    await db.commit()

    score_result = await db.execute(
        select(func.coalesce(func.sum(CommentVote.value), 0)).where(
            CommentVote.comment_id == comment.id
        )
    )
    score = int(score_result.scalar_one())
    user_vote = value if value != 0 else None
    return score, user_vote


async def report_comment(
    db: AsyncSession,
    *,
    comment: Comment,
    user_id: uuid.UUID,
) -> None:
    existing = await db.execute(
        select(CommentReport).where(
            CommentReport.user_id == user_id,
            CommentReport.comment_id == comment.id,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Comment already reported")

    db.add(CommentReport(user_id=user_id, comment_id=comment.id))
    await db.commit()
