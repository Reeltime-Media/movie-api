"""Blocking a comment author hides them from the blocker only."""

import asyncio
import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import ForbiddenError
from app.main import app
from app.services import comments as comments_service


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect())).lower()


class _Rows:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return self._rows


class _Scalars:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class _Db:
    def __init__(self, blocked=()):
        self.blocked = list(blocked)
        self.sql: list[str] = []
        self.committed = False

    async def execute(self, stmt):
        sql = _sql(stmt)
        self.sql.append(sql)
        if "from user_blocks" in sql:
            return _Scalars(self.blocked)
        return _Rows()

    async def scalar(self, stmt):
        self.sql.append(_sql(stmt))
        return 0

    async def commit(self):
        self.committed = True


def test_blocking_stores_one_idempotent_row():
    db = _Db()

    asyncio.run(comments_service.block_user(db, blocker_id=uuid.uuid4(), blocked_id=uuid.uuid4()))

    assert db.sql[0].startswith("insert into user_blocks")
    assert "on conflict do nothing" in db.sql[0]
    assert db.committed is True


def test_users_cannot_block_themselves():
    db = _Db()
    user_id = uuid.uuid4()

    with pytest.raises(ForbiddenError):
        asyncio.run(comments_service.block_user(db, blocker_id=user_id, blocked_id=user_id))

    assert db.committed is False


def _list(db, current_user_id):
    return asyncio.run(
        comments_service.list_comment_threads(
            db,
            content_id=uuid.uuid4(),
            current_user_id=current_user_id,
            page=1,
            page_size=5,
        )
    )


def test_blocked_authors_are_left_out_of_the_list_and_its_count():
    db = _Db(blocked=[uuid.uuid4()])

    _list(db, uuid.uuid4())

    queries = [sql for sql in db.sql if "from comments" in sql]
    assert len(queries) == 2
    assert all("user_id not in" in sql for sql in queries)


def test_guests_see_every_author():
    db = _Db()

    _list(db, None)

    assert not any("user_blocks" in sql for sql in db.sql)
    assert not any("user_id not in" in sql for sql in db.sql)


def test_replies_from_blocked_authors_are_left_out():
    db = _Db()
    root_id = uuid.uuid4()

    asyncio.run(
        comments_service.fetch_thread_rows_for_roots(
            db, uuid.uuid4(), [root_id], hidden_author_ids={uuid.uuid4()}
        )
    )

    assert all("user_id not in" in sql for sql in db.sql)


def test_block_author_route_is_registered():
    assert "post" in app.openapi()["paths"]["/comments/{comment_id}/block-author"]
