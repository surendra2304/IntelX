"""Database Session Management and Dependencies."""

import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from intelx.db.engine import get_async_engine
from intelx.db.models import ResearchRun

logger = logging.getLogger(__name__)

_sessionmaker: async_sessionmaker[AsyncSession] | None = None

# A boundary commit is retried this many times before the run is failed.
_RELEASE_ATTEMPTS = 4

# The only fields a stage boundary mutates, and therefore the only ones a
# rollback can lose. Restoring anything else would rewrite the whole row.
_BOUNDARY_FIELDS = ("status", "outcome", "error_json", "completed_at")


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Get or initialize the async session maker."""
    global _sessionmaker
    if _sessionmaker is None:
        engine = get_async_engine()
        _sessionmaker = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_health() -> bool:
    """Verify database connectivity by executing a lightweight query."""
    try:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return False


async def release_writer_lock(session: AsyncSession, run: ResearchRun) -> ResearchRun:
    """End the open write transaction so SQLite's single writer lock is freed.

    SQLite permits exactly one writer. A pipeline stage that performs external calls
    -- model gateways, web fetches -- must not hold this transaction across them, or
    every other writer (including concurrent research submissions) blocks for the
    whole stage and then fails with "database is locked".

    The orchestrator decides *when* a stage boundary is; this owns *how* the
    transaction ends, so the rule lives with the session rather than being restated
    at each call site.

    Concurrency makes the commit itself a contention point: several workers
    crossing boundaries at once contend for the same single writer, and a timeout
    here poisons the whole session. The commit is therefore retried on a lock
    error. Losing one uncommitted stage's worth of rows is acceptable; losing the
    run is not.
    """
    # A rollback discards everything uncommitted, which at a stage boundary is the
    # state transition the boundary exists to persist. Snapshot the run's columns
    # so the retry can restore them instead of continuing with the database saying
    # something the engine no longer believes.
    pending = {
        field: getattr(run, field)
        for field in _BOUNDARY_FIELDS
    }

    for attempt in range(_RELEASE_ATTEMPTS):
        try:
            await session.commit()
            break
        except OperationalError:
            await session.rollback()
            for field, value in pending.items():
                setattr(run, field, value)
            await session.flush()
            if attempt == _RELEASE_ATTEMPTS - 1:
                raise
            await asyncio.sleep(0.1 * (2**attempt))

    await session.refresh(run)
    return run
