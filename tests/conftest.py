"""Pytest configuration and test fixtures for INTELX."""

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Force testing configuration
os.environ["INTELX_ENV"] = "testing"
os.environ["INTELX_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["INTELX_MOCK_MODE"] = "true"

from intelx.app.factory import create_app
from intelx.core.settings import get_settings
from intelx.db.engine import dispose_engine


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Reset cached settings between test cases."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an asynchronous HTTP test client with ASGI transport."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    await dispose_engine()
