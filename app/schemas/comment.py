import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CommentAuthorRead(BaseModel):
    id: uuid.UUID
    display_name: str


class CommentRead(BaseModel):
    id: uuid.UUID
    content_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    body: str
    created_at: datetime
    updated_at: datetime
    author: CommentAuthorRead
    score: int = 0
    user_vote: int | None = None
    user_reported: bool = False


class CommentThreadRead(CommentRead):
    replies: list["CommentThreadRead"] = Field(default_factory=list)


CommentThreadRead.model_rebuild()


class CommentCreate(BaseModel):
    content_id: uuid.UUID
    body: str = Field(min_length=1, max_length=2000)
    parent_id: uuid.UUID | None = None


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class CommentVoteUpdate(BaseModel):
    value: int = Field(description="1 for upvote, -1 for downvote, 0 to remove vote")
