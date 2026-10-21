"""Tests for FRIDAY Universe Targeted Intelligence Endpoints (intelx/api/v1/friday_universe.py)."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from intelx.app.factory import create_app
from intelx.core.auth import hash_api_key
from intelx.core.enums import ApiKeyRole, SourceKind
from intelx.db.base import Base
from intelx.db.engine import get_async_engine
from intelx.db.models import ApiKey, Document
from intelx.db.repos import SourceRepo
from intelx.db.session import get_sessionmaker


@pytest_asyncio.fixture
async def universe_client() -> AsyncGenerator[AsyncClient, None]:
    """Test client for Friday Universe endpoints with initialized DB and seeded key."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        # Seed API key for test
        test_key = "universe-test-key-789"
        key_hash = hash_api_key(test_key)
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        existing_key = (await session.execute(stmt)).scalar_one_or_none()
        if not existing_key:
            session.add(
                ApiKey(
                    key_hash=key_hash,
                    name="universe-test-key",
                    role=ApiKeyRole.ADMIN,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

        # Seed sample documents with agent tags using SourceRepo.create_source
        src_stratex = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://test.market/btc-analysis",
            title="Bitcoin Institutional ETF Inflows Surge",
            publisher="Market Wire",
        )

        doc_stratex = Document(
            source_id=src_stratex.id,
            text=(
                "[FRIDAY_AGENT:STRATEX]\n"
                "[CATEGORY:MARKET]\n"
                "[PUBLISHER:Market Wire]\n"
                "\n"
                "Bitcoin spot ETFs registered over $1.2B in weekly net inflows.\n"
                "Institutional trading volumes continue to climb across exchanges."
            ),
            created_at=datetime.now(UTC),
        )
        session.add(doc_stratex)

        src_sentinel = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://test.security/cve-alert",
            title="Critical Kernel Vulnerability Patched",
            publisher="Security Bulletin",
        )

        doc_sentinel = Document(
            source_id=src_sentinel.id,
            text=(
                "[FRIDAY_AGENT:SENTINEL]\n"
                "[CATEGORY:SECURITY]\n"
                "[PUBLISHER:Security Bulletin]\n"
                "\n"
                "A remote code execution vulnerability in the container runtime was mitigated.\n"
                "Security teams are advised to deploy patches immediately."
            ),
            created_at=datetime.now(UTC),
        )
        session.add(doc_sentinel)
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": "universe-test-key-789"},
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_get_agent_intelligence_all(universe_client: AsyncClient):
    """Verify GET /api/v1/friday-universe/intelligence returns all tagged intelligence items."""
    res = await universe_client.get("/api/v1/friday-universe/intelligence?agent=all")
    assert res.status_code == 200
    data = res.json()
    assert data["agent"] == "all"
    assert data["total_items"] >= 2
    assert len(data["items"]) >= 2

    # Check item schema
    item = data["items"][0]
    assert "title" in item
    assert "url" in item
    assert "publisher" in item
    assert "agent" in item
    assert "category" in item
    assert "summary" in item
    assert "retrieved_at" in item


@pytest.mark.asyncio
async def test_get_agent_intelligence_targeted(universe_client: AsyncClient):
    """Verify filtering intelligence by specific agent tag."""
    # Stratex
    res = await universe_client.get("/api/v1/friday-universe/intelligence?agent=stratex")
    assert res.status_code == 200
    data = res.json()
    assert data["agent"] == "stratex"
    assert all(item["agent"] == "stratex" for item in data["items"])

    # Sentinel
    res_sentinel = await universe_client.get("/api/v1/friday-universe/intelligence?agent=sentinel")
    assert res_sentinel.status_code == 200
    data_sentinel = res_sentinel.json()
    assert data_sentinel["agent"] == "sentinel"
    assert any("Kernel Vulnerability" in item["title"] for item in data_sentinel["items"])


@pytest.mark.asyncio
async def test_get_agent_intelligence_invalid_agent(universe_client: AsyncClient):
    """Verify 400 error when querying unknown agent."""
    res = await universe_client.get("/api/v1/friday-universe/intelligence?agent=unknown_bot")
    assert res.status_code == 400
    assert "Invalid agent 'unknown_bot'" in res.json()["detail"]


@pytest.mark.asyncio
async def test_friday_universe_ingestion_status(universe_client: AsyncClient):
    """Verify GET /api/v1/friday-universe/status returns total counts and breakdown."""
    res = await universe_client.get("/api/v1/friday-universe/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "active"
    assert data["total_intelligence_items"] >= 2
    assert "by_agent" in data
    assert data["by_agent"]["stratex"] >= 1
    assert data["by_agent"]["sentinel"] >= 1


@pytest.mark.asyncio
async def test_trigger_autonomous_research(universe_client: AsyncClient):
    """Verify POST /api/v1/friday-universe/trigger-research queues investigation."""
    res = await universe_client.post("/api/v1/friday-universe/trigger-research?agent=stratex")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["run_id"] is not None
    assert data["target_agent"] == "stratex"
    assert "objective" in data


@pytest.mark.asyncio
async def test_post_agent_intelligence_task_envelope(universe_client: AsyncClient):
    """Verify POST /api/v1/friday-universe/intelligence accepts task envelopes and synthesizes citations."""
    envelope = {
        "task_id": "task_univ_123",
        "action": "research",
        "source_agent": "friday",
        "payload": {
            "query": "Assess crypto market liquidity and ETF flows",
        },
    }
    res = await universe_client.post("/api/v1/friday-universe/intelligence", json=envelope)
    assert res.status_code == 200
    data = res.json()
    assert data["task_id"] == "task_univ_123"
    assert data["target_agent"] == "intelx"
    assert data["source_agent"] == "friday"
    assert data["status"] == "SUCCESS"
    assert "result" in data
    assert data["result"]["citations_count"] >= 1
    assert len(data["result"]["sources"]) >= 1
    assert "execution_time_ms" in data
