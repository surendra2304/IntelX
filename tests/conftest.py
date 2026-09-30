"""Pytest configuration and test fixtures for INTELX."""

import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

TEST_DB_PATH = Path("./data/test_intelx.db").resolve()
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}"

# Force testing configuration
os.environ["INTELX_ENV"] = "testing"
os.environ["INTELX_DB_URL"] = TEST_DB_URL
os.environ["INTELX_MOCK_MODE"] = "true"

from intelx.app.factory import create_app  # noqa: E402
from intelx.core.settings import get_settings  # noqa: E402
from intelx.db.base import Base  # noqa: E402
from intelx.db.engine import get_async_engine  # noqa: E402


async def reset_test_schema(engine):
    """Drop and recreate all relational tables and FTS5 search indexes."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS chunks_fts;"))
        await conn.execute(text("DROP TABLE IF EXISTS claims_fts;"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id UNINDEXED, text);")
        )
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5("
                "id UNINDEXED, "
                "text, "
                "quote"
                ");"
            )
        )
        await conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS chunks_after_insert AFTER INSERT ON chunks BEGIN "
                "INSERT INTO chunks_fts(id, text) VALUES (new.id, new.text); "
                "END;"
            )
        )
        await conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS chunks_after_delete AFTER DELETE ON chunks BEGIN "
                "DELETE FROM chunks_fts WHERE id = old.id; "
                "END;"
            )
        )
        await conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS claims_after_insert AFTER INSERT ON claims BEGIN "
                "INSERT INTO claims_fts(id, text, quote) VALUES (new.id, new.text, new.quote); "
                "END;"
            )
        )
        await conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS claims_after_delete AFTER DELETE ON claims BEGIN "
                "DELETE FROM claims_fts WHERE id = old.id; "
                "END;"
            )
        )


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Reset cached settings between test cases."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def clean_database_per_test():
    """Reset test database tables cleanly before every test case."""
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = get_async_engine(TEST_DB_URL)
    await reset_test_schema(engine)
    yield


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an asynchronous HTTP test client with ASGI transport."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
