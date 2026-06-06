"""Step 1 of the async DB migration: prove the async engine, AsyncSession, and the
savepoint-isolated test fixture before any endpoint is converted.

The async stack runs alongside the untouched sync stack. These tests exercise the
real async engine (psycopg async over the same DATABASE_URL) and verify that the
fixture's outer-transaction rollback isolates tests the same way the sync
db_session does, which is the property the whole migration depends on.
"""

import pytest
from sqlalchemy import select, text

from app.models import Organization

pytestmark = pytest.mark.anyio

# A marker row used to prove cross-test isolation. If the fixture rolls back
# committed data, this name is absent at the start of every test regardless of
# order.
_MARKER = "async-savepoint-probe-org"


async def test_async_engine_connects(async_db_session):
    result = await async_db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


async def _probe_isolation(session) -> None:
    # Absent at the start: either never created, or a prior test's committed insert
    # was rolled back by the fixture teardown.
    before = await session.scalar(select(Organization).where(Organization.name == _MARKER))
    assert before is None

    # Commit within the savepoint, then read it back in the same session: proves
    # AsyncSession ORM writes and create_savepoint commits work.
    session.add(Organization(name=_MARKER))
    await session.commit()
    after = await session.scalar(select(Organization).where(Organization.name == _MARKER))
    assert after is not None and after.id is not None


async def test_async_savepoint_isolation_first(async_db_session):
    await _probe_isolation(async_db_session)


async def test_async_savepoint_isolation_second(async_db_session):
    # Order-independent: this passes only if the first test's committed marker was
    # rolled back before this test ran. Both tests assert a clean start, so the
    # isolation guarantee holds whichever runs first.
    await _probe_isolation(async_db_session)
