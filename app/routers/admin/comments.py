import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.dependencies import AdminUser, DBSession
from app.models.comment import Comment
from app.models.user import User
from app.schemas.comment import CommentRead, CommentUpdate
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.services.comments import (
    ensure_commentable_movie,
    get_comment_or_404,
    soft_delete_comment,
    to_comment_read,
    update_comment_body,
)
from app.services.pagination import paginate_query

router = APIRouter()


@router.get("/comments", response_model=PaginatedResponse[CommentRead])
async def list_admin_comments(
    content_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
    pagination: PaginationDep,
):
    await ensure_commentable_movie(db, content_id, allow_unpublished=True)

    stmt = (
        select(Comment, User)
        .join(User, Comment.user_id == User.id)
        .where(
            Comment.content_id == content_id,
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at.desc())
    )
    rows, total = await paginate_query(
        db,
        stmt,
        page=pagination.page,
        page_size=pagination.page_size,
        scalar=False,
    )
    items = [
        to_comment_read(comment, author)
        for comment, author in rows
    ]
    return build_paginated_response(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.patch("/comments/{comment_id}", response_model=CommentRead)
async def update_admin_comment(
    comment_id: uuid.UUID,
    data: CommentUpdate,
    db: DBSession,
    _: AdminUser,
):
    comment = await get_comment_or_404(db, comment_id)
    await ensure_commentable_movie(db, comment.content_id, allow_unpublished=True)

    author_result = await db.execute(select(User).where(User.id == comment.user_id))
    author = author_result.scalar_one()
    comment = await update_comment_body(db, comment, data.body)
    return to_comment_read(comment, author)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_admin_comment(
    comment_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    comment = await get_comment_or_404(db, comment_id)
    await soft_delete_comment(db, comment)
