"""Database engine configuration for INTELX.

INTELX persists to Oracle Autonomous Database only. A SQLite engine is built
only when the test suite passes an explicit URL, so a misconfigured deployment
fails closed instead of quietly writing to a local file.
"""

import logging
import os
import sys
from typing import Any

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


def _is_test_environment() -> bool:
    return "pytest" in sys.modules or os.getenv("INTELX_ENV", "").lower() in {
        "test",
        "testing",
    }


def get_async_engine(db_url: str | None = None) -> AsyncEngine:
    """Create or return the process-wide async engine.

    ``db_url`` is honoured only by the test suite, which passes an explicit
    SQLite file. Runtime callers always resolve the Oracle DSN from settings.
    """
    global _engine
    if _engine is not None:
        return _engine

    url = (db_url or get_settings().DB_URL).strip()
    if not url:
        raise RuntimeError(
            "INTELX_DB_URL is not configured. Set an oracle+oracledb:// DSN for "
            "Oracle Autonomous Database."
        )

    lowered = url.lower()
    if lowered.startswith("sqlite"):
        if db_url is None or not _is_test_environment():
            raise RuntimeError(
                "INTELX refuses to start on SQLite outside the test suite. "
                "Configure an oracle+oracledb:// DSN."
            )
        _engine = create_async_engine(url, echo=False, future=True)
        logger.info("Test database engine initialised on an explicit SQLite path.")
        return _engine

    if lowered.startswith(("postgres://", "postgresql")):
        raise RuntimeError(
            "PostgreSQL is not a supported backend. Configure an "
            "oracle+oracledb:// DSN for Oracle Autonomous Database."
        )

    if not lowered.startswith("oracle"):
        raise RuntimeError(
            f"Unsupported database backend in INTELX_DB_URL: {url.split('://')[0]}. "
            "Oracle Autonomous Database is the only supported backend."
        )

    engine_kwargs: dict[str, Any] = {
        "echo": False,
        "future": True,
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 300,
    }
    _engine = create_async_engine(url, **engine_kwargs)
    logger.info("Database engine initialised for: %s", url.split("@")[-1])
    return _engine


async def dispose_engine() -> None:
    """Gracefully dispose and close the async engine connections."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("Database engine disposed.")
