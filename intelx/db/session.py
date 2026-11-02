import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from intelx.db.engine import get_async_engine
from intelx.db.models import ResearchRun

logger = logging.getLogger(__name__)

_sessionmaker: async_sessionmaker[AsyncSession] | None = None
# Serialises write transactions. Oracle handles concurrent writers, but the
# research pipeline still stages long external calls between flushes; holding
# one writer at a time keeps transaction boundaries predictable and bounded.
_WRITE_LOCK = asyncio.Lock()


def get_write_lock() -> asyncio.Lock:
    """Return the process-wide mutex that serialises research write transactions."""
    return _WRITE_LOCK


def get_sqlite_write_lock() -> asyncio.Lock:
    """Backwards-compatible alias for :func:`get_write_lock`."""
    return _WRITE_LOCK


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
            bind = session.get_bind()
            dialect = getattr(bind, "dialect", None)
            statement = (
                "SELECT 1 FROM DUAL" if dialect is not None and dialect.name == "oracle" else "SELECT 1"
            )
            result = await session.execute(text(statement))
            return result.scalar() == 1
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return False


async def release_writer_lock(session: AsyncSession, run: ResearchRun) -> ResearchRun:
    """End the open write transaction so the writer lock is released."""
    async with get_write_lock():
        await session.commit()
    return run
