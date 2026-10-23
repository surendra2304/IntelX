"""Database Engine Configuration with SQLite WAL Support."""

import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import JSON

from intelx.core.settings import get_settings


@compiles(JSON, "oracle")
def _compile_json_oracle(_type, _compiler, **_kw):
    """Oracle 23ai natively supports the JSON data type."""
    return "JSON"


# Fallback safety patch for older compiler implementations
try:
    from sqlalchemy.dialects.oracle.base import OracleTypeCompiler

    OracleTypeCompiler.visit_JSON = lambda self, type_, **kw: "JSON"
    OracleTypeCompiler.visit_json = lambda self, type_, **kw: "JSON"
except Exception:
    pass

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None


def configure_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Set SQLite pragmas for optimal concurrent performance and integrity."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    # WAL lets readers proceed during a write but still permits only one writer.
    # A 60s busy_timeout turned ordinary write contention into a 60-second stall that
    # then surfaced as "database is locked" and a 500, so concurrent research
    # submissions hung instead of being rejected or serialized promptly.
    cursor.execute("PRAGMA busy_timeout = 5000;")
    cursor.close()


def get_async_engine(db_url: str | None = None) -> AsyncEngine:
    """Create or return existing async database engine."""
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = db_url or settings.DB_URL

    # Normalize Oracle URL to async driver
    if url.startswith("oracle+oracledb://"):
        url = "oracle+oracledb_async://" + url[len("oracle+oracledb://") :]
    elif url.startswith("oracle://"):
        url = "oracle+oracledb_async://" + url[len("oracle://") :]

    # Invariant 2 (Zero-Disk SQLite): On Linux with /dev/shm, redirect local SQLite fallback to RAM tmpfs
    if (
        os.name != "nt"
        and "sqlite" in url
        and os.path.exists("/dev/shm")
        and not url.startswith("sqlite+aiosqlite:////dev/shm")
        and ":memory:" not in url
    ):
        if "data/intelx.db" in url or "./data" in url:
            url = "sqlite+aiosqlite:////dev/shm/intelx.db"

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
        # Matches the busy_timeout above; a long connect timeout just deferred the
        # same stall to the moment a connection was first requested.
        engine_kwargs["connect_args"] = {"timeout": 5.0, "check_same_thread": False}
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            engine_kwargs["poolclass"] = StaticPool
        _engine = create_async_engine(url, **engine_kwargs)
        event.listen(_engine.sync_engine, "connect", configure_sqlite_pragmas)
    else:
        # PostgreSQL / other async engines
        _engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=300,
            **engine_kwargs,
        )

    logger.info(f"Database engine initialized for: {url.split('@')[-1]}")
    return _engine


async def dispose_engine() -> None:
    """Gracefully dispose and close the async engine connections."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("Database engine disposed.")
