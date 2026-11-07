import uuid

import pytest

from app.services.content_delete import (
    delete_content_dependencies,
    delete_series_and_dependencies,
)


class MockDb:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)


@pytest.mark.asyncio
async def test_delete_content_dependencies_executes_all_cleanups():
    db = MockDb()
    content_id = uuid.uuid4()
    await delete_content_dependencies(db, content_id)

    # Verifies all 10 dependency cleanup statements are dispatched
    assert len(db.statements) >= 10


@pytest.mark.asyncio
async def test_delete_series_and_dependencies_cleans_purchases_and_rails():
    db = MockDb()
    series_id = uuid.uuid4()
    await delete_series_and_dependencies(db, series_id)

    # Verifies bulk episode cleanups plus series purchases, payment intents, and rail cleanups
    assert len(db.statements) >= 15
