"""Comprehensive tests for Top-Level API Router: Task Execution, Search, Scrape, Summarize."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.core.auth import hash_api_key
from intelx.core.enums import (
    ApiKeyRole,
    ClaimOrigin,
    ClaimStatus,
    ClaimType,
    RunOutcome,
    RunStatus,
    SourceKind,
    TrustTier,
)
from intelx.db.engine import get_async_engine
from intelx.db.models import ApiKey, Chunk, Claim, Document, Finding, ResearchRun, Source
from intelx.db.session import get_sessionmaker


@pytest_asyncio.fixture
async def router_clients():
    """Provide admin and member authenticated test clients for top-level router routes."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        from intelx.db.base import Base

        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        admin_hash = hash_api_key("router-admin-key")
        member_hash = hash_api_key("router-member-key")

        session.add(
            ApiKey(
                key_hash=admin_hash,
                name="router-admin",
                role=ApiKeyRole.ADMIN,
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            ApiKey(
                key_hash=member_hash,
                name="router-member",
                role=ApiKeyRole.MEMBER,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    admin_headers = {"Authorization": "Bearer router-admin-key"}
    member_headers = {"Authorization": "Bearer router-member-key"}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, admin_headers, member_headers


@pytest.mark.asyncio
async def test_task_execute_cancel_lifecycle(router_clients):
    """Verify task cancellation authorization, conflict detection, and receipts."""
    client, admin_headers, member_headers = router_clients
    sessionmaker = get_sessionmaker()

    # 1. Create a queued run owned by 'router-member'
    async with sessionmaker() as session:
        run = ResearchRun(
            id="run-cancel-test-01",
            objective="Evaluating solid state batteries",
            status=RunStatus.QUEUED,
            created_by="router-member",
        )
        session.add(run)
        await session.commit()

    # 2. Another non-admin user cannot cancel someone else's run -> 404
    async with sessionmaker() as session:
        other_hash = hash_api_key("router-stranger-key")
        session.add(
            ApiKey(
                key_hash=other_hash,
                name="router-stranger",
                role=ApiKeyRole.MEMBER,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    stranger_headers = {"Authorization": "Bearer router-stranger-key"}
    resp_404 = await client.post(
        "/v1/task/execute",
        json={"action": "cancel", "payload": {"run_id": "run-cancel-test-01"}},
        headers=stranger_headers,
    )
    assert resp_404.status_code == 404

    # 3. Owner cancels run successfully -> 200
    resp_cancel = await client.post(
        "/v1/task/execute",
        json={"action": "cancel", "payload": {"run_id": "run-cancel-test-01"}},
        headers=member_headers,
    )
    assert resp_cancel.status_code == 200
    body = resp_cancel.json()
    assert body["status"] == "CANCELLED"
    assert body["receipt"]["requested_action"] == "cancel"

    # 4. Attempting to cancel already terminal run -> 409 Conflict
    resp_409 = await client.post(
        "/v1/task/execute",
        json={"action": "cancel", "payload": {"run_id": "run-cancel-test-01"}},
        headers=member_headers,
    )
    assert resp_409.status_code == 409


@pytest.mark.asyncio
async def test_task_execute_research_with_evidence_and_citations(router_clients):
    """Verify research action synthesizes completed runs, findings, claims, and citations."""
    client, admin_headers, _ = router_clients
    sessionmaker = get_sessionmaker()

    # Seed a completed research run with source, claims, and findings
    run_id = "run-evidence-synthesis-01"
    src_id = "src-battery-journal-01"
    clm_id1 = "clm-energy-density-01"
    clm_id2 = "clm-thermal-margin-02"

    async with sessionmaker() as session:
        run = ResearchRun(
            id=run_id,
            objective="Deep analysis of sodium-ion cathode benchmarks and thermal thresholds",
            status=RunStatus.COMPLETED,
            outcome=RunOutcome.ANSWERED,
            created_by="router-admin",
            created_at=datetime.now(UTC),
        )
        source = Source(
            id=src_id,
            kind=SourceKind.WEB,
            location="https://journal.energy.org/article-01",
            domain="journal.energy.org",
            title="Next-Gen Sodium Cathode Benchmarks",
            publisher="Energy Journal",
            trust_tier=TrustTier.TRUSTED,
            fingerprint="sha256-battery-article-01",
            created_by_run_id=run_id,
        )
        doc = Document(
            id="doc-01",
            source_id=src_id,
            text="Layered oxide sodium cathodes deliver 165 mAh/g specific capacity. Thermal runaway initiation is delayed to 165°C.",
            language="en",
        )
        chk = Chunk(
            id="chk-01",
            document_id="doc-01",
            idx=0,
            start_char=0,
            end_char=120,
            text="Layered oxide sodium cathodes deliver 165 mAh/g specific capacity. Thermal runaway initiation is delayed to 165°C.",
        )
        claim1 = Claim(
            id=clm_id1,
            run_id=run_id,
            source_id=src_id,
            document_id="doc-01",
            chunk_id="chk-01",
            text="Layered oxide sodium cathodes deliver 165 mAh/g specific capacity.",
            quote="Layered oxide sodium cathodes deliver 165 mAh/g specific capacity.",
            span_start=0,
            span_end=66,
            claim_type=ClaimType.MEASUREMENT,
            origin=ClaimOrigin.EXTRACTED,
            status=ClaimStatus.ACTIVE,
            confidence=0.95,
            created_by_agent="ExtractorAgent",
        )
        claim2 = Claim(
            id=clm_id2,
            run_id=run_id,
            source_id=src_id,
            document_id="doc-01",
            chunk_id="chk-01",
            text="Thermal runaway initiation is delayed to 165°C.",
            quote="Thermal runaway initiation is delayed to 165°C.",
            span_start=100,
            span_end=147,
            claim_type=ClaimType.MEASUREMENT,
            origin=ClaimOrigin.EXTRACTED,
            status=ClaimStatus.ACTIVE,
            confidence=0.92,
            created_by_agent="ExtractorAgent",
        )
        finding = Finding(
            id="fnd-battery-summary-01",
            run_id=run_id,
            conclusion="Sodium-ion batteries demonstrate acceptable capacity with high thermal safety margins.",
            confidence=0.94,
            claim_ids_json=[clm_id1, clm_id2],
        )
        session.add_all([run, source])
        await session.flush()
        session.add(doc)
        await session.flush()
        session.add(chk)
        await session.flush()
        session.add_all([claim1, claim2, finding])
        await session.commit()

    # Query matching the run objective
    resp = await client.post(
        "/v1/task/execute",
        json={
            "task_id": "task_research_evidence_test",
            "action": "research",
            "payload": {"query": "sodium-ion cathode thermal"},
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["result"]["findings_count"] >= 1
    assert data["result"]["citations_count"] >= 1
    assert len(data["result"]["provenance_chain"]) >= 2
    assert "spoken_summary" in data["result"]
    assert "text_response" in data["result"]


@pytest.mark.asyncio
async def test_api_search_endpoint(router_clients):
    """Verify /search for empty queries, database hits, web search fallback, and failure resilience."""
    client, admin_headers, _ = router_clients

    # 1. Empty query
    resp_empty = await client.post("/search", json={"query": " "}, headers=admin_headers)
    assert resp_empty.status_code == 422 or resp_empty.json()["total_results"] == 0

    # GET without query returns empty result
    resp_get_empty = await client.get("/search", headers=admin_headers)
    assert resp_get_empty.status_code == 200
    assert resp_get_empty.json()["total_results"] == 0

    # 2. Web search fallback when results < limit
    mock_hit = MagicMock()
    mock_hit.title = "Live Web Result"
    mock_hit.url = "https://live-search.org/result"
    mock_hit.snippet = "A live search snippet from duckduckgo"

    with patch(
        "intelx.connectors.search.WebSearchConnector.fetch",
        new_callable=AsyncMock,
        return_value=[mock_hit],
    ):
        resp_web = await client.post(
            "/search",
            json={"query": "quantum computing breakthroughs 2026", "limit": 5},
            headers=admin_headers,
        )
        assert resp_web.status_code == 200
        data = resp_web.json()
        assert data["web_search_status"] == "ok"
        assert any(r["url"] == "https://live-search.org/result" for r in data["results"])

    # 3. Web search failure resilience
    with patch(
        "intelx.connectors.search.WebSearchConnector.fetch",
        side_effect=RuntimeError("Search engine offline"),
    ):
        resp_fail = await client.post(
            "/search",
            json={"query": "unreachable query test", "limit": 5},
            headers=admin_headers,
        )
        assert resp_fail.status_code == 200
        assert resp_fail.json()["web_search_status"] == "unavailable"


@pytest.mark.asyncio
async def test_api_scrape_endpoint(router_clients):
    """Verify /scrape for robots.txt denials, HTML parsing, content length, and exception handling."""
    client, admin_headers, _ = router_clients

    # 1. Robots.txt denial
    mock_robots_denied = MagicMock()
    mock_robots_denied.robots_ok = False
    mock_robots_denied.error = "Disallowed by robots.txt"
    mock_robots_denied.status_code = 403

    with patch(
        "intelx.connectors.web.HttpFetchConnector.fetch",
        new_callable=AsyncMock,
        return_value=mock_robots_denied,
    ):
        resp_robots = await client.post(
            "/scrape",
            json={"url": "https://protected-site.com/private"},
            headers=admin_headers,
        )
        assert resp_robots.status_code == 200
        data = resp_robots.json()
        assert data["status"] == "error"
        assert "robots.txt" in data["error"]

    # 2. Successful HTML scrape with title extraction
    html_bytes = b"<html><head><title>Quantum Battery Lab</title></head><body>Energy Density: 400 Wh/kg</body></html>"
    mock_fetch_ok = MagicMock()
    mock_fetch_ok.robots_ok = True
    mock_fetch_ok.content = html_bytes
    mock_fetch_ok.content_type = "text/html; charset=utf-8"
    mock_fetch_ok.final_url = "https://lab.org/batteries"
    mock_fetch_ok.status_code = 200

    with patch(
        "intelx.connectors.web.HttpFetchConnector.fetch",
        new_callable=AsyncMock,
        return_value=mock_fetch_ok,
    ):
        resp_ok = await client.post(
            "/scrape",
            json={"url": "https://lab.org/batteries"},
            headers=admin_headers,
        )
        assert resp_ok.status_code == 200
        data = resp_ok.json()
        assert data["status"] == "ok"
        assert data["title"] == "Quantum Battery Lab"
        assert "Energy Density" in data["text"]

    # 3. Scrape failure / exception
    with patch(
        "intelx.connectors.web.HttpFetchConnector.fetch",
        side_effect=ConnectionResetError("Socket reset"),
    ):
        resp_err = await client.post(
            "/scrape",
            json={"url": "https://down-site.com"},
            headers=admin_headers,
        )
        assert resp_err.status_code == 200
        assert resp_err.json()["status"] == "error"


@pytest.mark.asyncio
async def test_api_summarize_endpoint(router_clients):
    """Verify /summarize with direct text truncation and database claim retrieval."""
    client, admin_headers, _ = router_clients

    # 1. Direct text shorter than max_length
    resp_short = await client.post(
        "/summarize",
        json={
            "text": "Sodium-ion cells demonstrate exceptional cold temperature performance.",
            "max_length": 100,
        },
        headers=admin_headers,
    )
    assert resp_short.status_code == 200
    assert resp_short.json()["summary"].endswith("performance.")

    # 2. Direct text longer than max_length -> truncated with '...'
    long_text = "Word " * 50
    resp_long = await client.post(
        "/summarize",
        json={"text": long_text, "max_length": 20},
        headers=admin_headers,
    )
    assert resp_long.status_code == 200
    assert resp_long.json()["summary"].endswith("...")

    # 3. Query with no text provided (searches claims in database)
    resp_query = await client.post(
        "/summarize",
        json={"query": "nonexistent query string 99999"},
        headers=admin_headers,
    )
    assert resp_query.status_code == 200
    assert "No verified claims found" in resp_query.json()["summary"]
