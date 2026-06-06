import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.dependencies import CurrentUser, DBSession, OptionalUser
from app.models.comment import Comment
from app.models.user import User
from app.schemas.comment import (
    CommentCreate,
    CommentRead,
    CommentThreadRead,
    CommentVoteUpdate,
)
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services.comments import (
    ensure_commentable_movie,
    get_comment_or_404,
    list_comment_threads,
    report_comment,
    set_comment_vote,
    to_comment_read,
    validate_parent_comment,
)

router = APIRouter(prefix="/comments", tags=["comments"])


@router.get("/", response_model=PaginatedResponse[CommentThreadRead])
async def list_comments(
    content_id: uuid.UUID,
    db: DBSession,
    current_user: OptionalUser,
    pagination: PaginationDep,
):
    await ensure_commentable_movie(db, content_id)
    items, total = await list_comment_threads(
        db,
        content_id=content_id,
        current_user_id=current_user.id if current_user else None,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return build_paginated_response(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("/", response_model=CommentRead, status_code=201)
async def create_comment(
    data: CommentCreate,
    db: DBSession,
    current_user: CurrentUser,
):
    await ensure_commentable_movie(db, data.content_id)
    await validate_parent_comment(db, content_id=data.content_id, parent_id=data.parent_id)

    comment = Comment(
        user_id=current_user.id,
        content_id=data.content_id,
        parent_id=data.parent_id,
        body=data.body.strip(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return to_comment_read(comment, current_user)


@router.put("/{comment_id}/vote", response_model=CommentRead)
async def vote_comment(
    comment_id: uuid.UUID,
    data: CommentVoteUpdate,
    db: DBSession,
    current_user: CurrentUser,
):
    if data.value not in (-1, 0, 1):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vote must be 1, -1, or 0",
        )

    comment = await get_comment_or_404(db, comment_id)
    await ensure_commentable_movie(db, comment.content_id)

    score, user_vote = await set_comment_vote(
        db, comment=comment, user_id=current_user.id, value=data.value
    )

    author_result = await db.execute(select(User).where(User.id == comment.user_id))
    author = author_result.scalar_one()
    return to_comment_read(comment, author, score=score, user_vote=user_vote)


@router.post("/{comment_id}/report", status_code=204)
async def report_comment_endpoint(
    comment_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    comment = await get_comment_or_404(db, comment_id)
    await ensure_commentable_movie(db, comment.content_id)
    await report_comment(db, comment=comment, user_id=current_user.id)
