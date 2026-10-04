"""Database Session Management and Dependencies."""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from intelx.db.engine import get_async_engine
from intelx.db.models import ResearchRun

logger = logging.getLogger(__name__)

_sessionmaker: async_sessionmaker[AsyncSession] | None = None


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
    """
    await session.commit()
    await session.refresh(run)
    return run
