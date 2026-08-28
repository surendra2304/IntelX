"""Database Engine Configuration with SQLite WAL Support."""

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from intelx.core.settings import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None


def configure_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Set SQLite pragmas for optimal concurrent performance and integrity."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA busy_timeout = 5000;")
    cursor.close()


def get_async_engine(db_url: str | None = None) -> AsyncEngine:
    """Create or return existing async database engine."""
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = db_url or settings.DB_URL

    # Ensure parent directory exists for SQLite database files
    if "sqlite" in url:
        # Extract relative path if standard file format
        db_path_str = url.split(":///")[-1]
        if db_path_str and not db_path_str.startswith(":memory:"):
            db_path = Path(db_path_str).resolve()
            db_path.parent.mkdir(parents=True, exist_ok=True)

    engine_kwargs: dict[str, Any] = {
        "echo": False,
        "future": True,
    }

    if "sqlite" in url:
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            engine_kwargs["poolclass"] = StaticPool
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_async_engine(url, **engine_kwargs)
        event.listen(_engine.sync_engine, "connect", configure_sqlite_pragmas)
    else:
        # PostgreSQL / other async engines
        _engine = create_async_engine(url, pool_pre_ping=True, **engine_kwargs)

    logger.info(f"Database engine initialized for: {url.split('@')[-1]}")
    return _engine


async def dispose_engine() -> None:
    """Gracefully dispose and close the async engine connections."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("Database engine disposed.")
