"""Tests for FRIDAY Delegation and Consumer API Endpoints."""

import json
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from intelx.app.factory import create_app
from intelx.core.auth import friday_rate_limiter, hash_api_key
from intelx.core.enums import (
    ApiKeyRole,
    ArtifactFormat,
    ArtifactType,
    ClaimStatus,
    ClaimType,
    RunOutcome,
    RunStatus,
    SourceKind,
)
from intelx.db.base import Base
from intelx.db.engine import get_async_engine
from intelx.db.models import (
    ApiKey,
    Artifact,
    Finding,
)
from intelx.db.repos import ClaimRepo, RunRepo, SourceRepo
from intelx.db.session import get_sessionmaker


@pytest_asyncio.fixture
async def friday_test_client():
    """Create test client with database tables and seeded keys initialized."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        # Seed test Friday key
        f_hash = hash_api_key("friday-test-secret-key-123")
        stmt = select(ApiKey).where(ApiKey.key_hash == f_hash)
        if not (await session.execute(stmt)).scalar_one_or_none():
            session.add(
                ApiKey(
                    key_hash=f_hash,
                    name="friday-integration-key",
                    role=ApiKeyRole.MEMBER,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_friday_research_delegation_post_and_queue_priority(friday_test_client):
    """Verify POST /api/v1/friday/research enqueues job and priority handling works."""
    headers = {"X-API-Key": "friday-test-secret-key-123"}

    # 1. Enqueue normal priority job
    normal_payload = {
        "friday_request_id": "req-normal-001",
        "question": "Normal priority investigation on market dynamics",
        "context": {
            "requesting_system": "friday",
            "priority": "normal",
            "domain_hint": "market",
        },
        "depth": "quick_scan",
        "budget": {"max_sources": 5, "max_time_minutes": 5},
    }
    res_normal = await friday_test_client.post(
        "/api/v1/friday/research",
        json=normal_payload,
        headers=headers,
    )
    assert res_normal.status_code == 201
    data_normal = res_normal.json()
    assert data_normal["friday_request_id"] == "req-normal-001"
    assert data_normal["status"] == "QUEUED"
    assert data_normal["subquestion_count"] == 2
    normal_run_id = data_normal["intelx_run_id"]
    assert normal_run_id is not None

    # 2. Enqueue urgent priority job afterwards
    urgent_payload = {
        "friday_request_id": "req-urgent-999",
        "question": "Urgent security vulnerability assessment",
        "context": {
            "requesting_system": "sentinel",
            "priority": "urgent",
            "related_incident_id": "inc-404-sec",
            "domain_hint": "security",
        },
        "depth": "deep_dive",
        "budget": {"max_sources": 15, "max_time_minutes": 20},
        "webhook_url": "https://friday.internal/webhook/inc-404",
    }
    res_urgent = await friday_test_client.post(
        "/api/v1/friday/research",
        json=urgent_payload,
        headers=headers,
    )
    assert res_urgent.status_code == 201
    data_urgent = res_urgent.json()
    assert data_urgent["friday_request_id"] == "req-urgent-999"
    assert data_urgent["subquestion_count"] == 6
    urgent_run_id = data_urgent["intelx_run_id"]

    # 3. Verify priority queue claiming: urgent run must be claimed BEFORE normal run
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        claimed_run = await RunRepo.get_or_claim_next_queued_job(session)
        assert claimed_run is not None
        assert claimed_run.id == urgent_run_id
        assert claimed_run.status == RunStatus.PLANNING


@pytest.mark.asyncio
async def test_friday_research_status_and_progress(friday_test_client):
    """Verify GET /api/v1/friday/research/{run_id} returns status, phase, and progress."""
    headers = {"Authorization": "Bearer friday-test-secret-key-123"}
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective="Status test objective",
            scope_json={"friday_request_id": "req-stat-101", "depth": "standard"},
        )
        run.status = RunStatus.EXTRACTING
        run.usd_cost = 0.0152

        # Create dummy source and claims
        src = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://arxiv.org/abs/2401.12345",
            title="Layered Oxide Paper",
        )
        doc = await SourceRepo.create_document(session, src.id, "Document text here")
        quote_text = "Document text"
        chunk = await SourceRepo.create_chunk(session, doc.id, 0, 0, len(quote_text), quote_text)

        await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=src.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            text_content="Active claim 1",
            quote=quote_text,
            span_start=0,
            span_end=len(quote_text),
            claim_type=ClaimType.FACT,
            status=ClaimStatus.ACTIVE,
        )
        await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=src.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            text_content="Disputed claim 2",
            quote=quote_text,
            span_start=0,
            span_end=len(quote_text),
            claim_type=ClaimType.FACT,
            status=ClaimStatus.DISPUTED,
        )
        await session.commit()
        run_id = run.id

    res = await friday_test_client.get(f"/api/v1/friday/research/{run_id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["run_id"] == run_id
    assert data["friday_request_id"] == "req-stat-101"
    assert data["status"] == "EXTRACTING"
    assert data["current_phase"] == "extraction"
    assert data["claims_count"] == 2
    assert data["contradiction_count"] == 1
    assert data["usd_cost"] == 0.0152


@pytest.mark.asyncio
async def test_friday_research_findings_and_citations(friday_test_client):
    """Verify GET /api/v1/friday/research/{run_id}/findings resolves citations."""
    headers = {"X-API-Key": "friday-test-secret-key-123"}
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective="Findings test objective",
            scope_json={"friday_request_id": "req-findings-202"},
        )
        src = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://nature.com/articles/battery-review",
            title="Nature Battery Review 2026",
        )
        doc_str = "Sodium energy density reaches 160 Wh/kg."
        doc = await SourceRepo.create_document(session, src.id, doc_str)
        chunk = await SourceRepo.create_chunk(session, doc.id, 0, 0, len(doc_str), doc_str)

        cl = await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=src.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            text_content="Sodium-ion cells achieve 160 Wh/kg gravimetric energy density.",
            quote=doc_str,
            span_start=0,
            span_end=len(doc_str),
            claim_type=ClaimType.FACT,
            confidence=0.92,
            status=ClaimStatus.ACTIVE,
        )

        finding = Finding(
            run_id=run.id,
            conclusion="Sodium-ion layered oxides demonstrate viable commercial gravimetric energy density.",
            confidence=0.88,
            confidence_method="v1-composite",
            claim_ids_json=[cl.id],
            gaps_json=[],
            contradictions_json=[],
            unverified_json=[],
        )
        session.add(finding)
        await session.commit()
        run_id = run.id

    res = await friday_test_client.get(
        f"/api/v1/friday/research/{run_id}/findings", headers=headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["run_id"] == run_id
    assert len(data["findings"]) == 1
    f_item = data["findings"][0]
    assert "Sodium-ion layered oxides" in f_item["statement"]
    assert f_item["confidence_score"] == 0.88
    assert f_item["status"] == "verified"
    assert f_item["evidence_count"] == 1
    assert len(f_item["citations"]) == 1
    cit = f_item["citations"][0]
    assert cit["source_title"] == "Nature Battery Review 2026"
    assert cit["source_url"] == "https://nature.com/articles/battery-review"
    assert cit["verbatim_span"] == "Sodium energy density reaches 160 Wh/kg."


@pytest.mark.asyncio
async def test_friday_research_report_and_contradictions(friday_test_client, tmp_path):
    """Verify GET report and GET contradictions endpoints."""
    headers = {"X-API-Key": "friday-test-secret-key-123"}
    sessionmaker = get_sessionmaker()

    # Create dummy artifact files
    report_md_path = tmp_path / "report.md"
    report_md_path.write_text("# Research Report\n\nExecutive Summary text.", encoding="utf-8")
    report_json_path = tmp_path / "report.json"
    report_json_path.write_text(
        json.dumps({"summary": "Verified battery intelligence"}), encoding="utf-8"
    )

    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective="Contradictions and report test",
        )
        art_md = Artifact(
            run_id=run.id,
            type=ArtifactType.REPORT,
            format=ArtifactFormat.MD,
            path=str(report_md_path),
            sha256="md-hash",
        )
        art_json = Artifact(
            run_id=run.id,
            type=ArtifactType.REPORT,
            format=ArtifactFormat.JSON,
            path=str(report_json_path),
            sha256="json-hash",
        )
        session.add(art_md)
        session.add(art_json)

        src1 = await SourceRepo.create_source(
            session, SourceKind.WEB, "https://lab1.org/data", title="Lab 1"
        )
        src2 = await SourceRepo.create_source(
            session, SourceKind.WEB, "https://lab2.org/data", title="Lab 2"
        )

        t1 = "Cathode A density is 160 Wh/kg."
        t2 = "Cathode A density is 120 Wh/kg."
        doc1 = await SourceRepo.create_document(session, src1.id, t1)
        doc2 = await SourceRepo.create_document(session, src2.id, t2)
        c1 = await SourceRepo.create_chunk(session, doc1.id, 0, 0, len(t1), t1)
        c2 = await SourceRepo.create_chunk(session, doc2.id, 0, 0, len(t2), t2)

        cl1 = await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=src1.id,
            document_id=doc1.id,
            chunk_id=c1.id,
            text_content="Cathode A achieves 160 Wh/kg.",
            quote=t1,
            span_start=0,
            span_end=len(t1),
            claim_type=ClaimType.FACT,
            subject="Cathode A",
            status=ClaimStatus.DISPUTED,
        )
        cl2 = await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=src2.id,
            document_id=doc2.id,
            chunk_id=c2.id,
            text_content="Cathode A achieves only 120 Wh/kg.",
            quote=t2,
            span_start=0,
            span_end=len(t2),
            claim_type=ClaimType.FACT,
            subject="Cathode A",
            status=ClaimStatus.DISPUTED,
        )
        assert cl1.id != cl2.id
        await session.commit()
        run_id = run.id

    # 1. Test Report endpoint
    res_rep = await friday_test_client.get(
        f"/api/v1/friday/research/{run_id}/report", headers=headers
    )
    assert res_rep.status_code == 200
    rep_data = res_rep.json()
    assert "# Research Report" in rep_data["report_markdown"]
    assert rep_data["report_json"]["summary"] == "Verified battery intelligence"
    assert rep_data["citations_resolved"] is True

    # 2. Test Contradictions endpoint
    res_cont = await friday_test_client.get(
        f"/api/v1/friday/research/{run_id}/contradictions", headers=headers
    )
    assert res_cont.status_code == 200
    cont_data = res_cont.json()
    assert cont_data["contradiction_count"] >= 1
    c_pair = cont_data["contradictions"][0]
    assert "Cathode A" in c_pair["topic_or_subject"]
    assert c_pair["claim_a"]["source_title"] == "Lab 1"
    assert c_pair["claim_b"]["source_title"] == "Lab 2"


@pytest.mark.asyncio
async def test_friday_research_events_sse_stream(friday_test_client):
    """Verify GET /api/v1/friday/research/{run_id}/events returns SSE stream chunks."""
    headers = {"X-API-Key": "friday-test-secret-key-123"}
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective="SSE stream test",
        )
        run.status = RunStatus.COMPLETED
        run.outcome = RunOutcome.ANSWERED

        await RunRepo.add_event(
            session=session,
            run_id=run.id,
            event_type="claim.extracted",
            payload_json={"claim_count": 3},
        )
        await session.commit()
        run_id = run.id

    res = await friday_test_client.get(f"/api/v1/friday/research/{run_id}/events", headers=headers)
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    text = res.text
    assert "event: run_started" in text
    assert "event: claim_extracted" in text
    assert "event: report_ready" in text


@pytest.mark.asyncio
async def test_friday_auth_and_rate_limiting(friday_test_client):
    """Verify Friday API rejects unauthenticated requests and enforces 50 req/hour limit."""
    # 1. Reject without key
    res_no_auth = await friday_test_client.get("/api/v1/friday/research/non_existent_run")
    assert res_no_auth.status_code == 401

    # 2. Reject with invalid key
    res_bad_auth = await friday_test_client.get(
        "/api/v1/friday/research/non_existent_run",
        headers={"X-API-Key": "completely-invalid-key-999"},
    )
    assert res_bad_auth.status_code == 401

    # 3. Rate limiter triggers 429 when exhausted
    test_key_hash = hash_api_key("rate-limited-friday-key")
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        session.add(
            ApiKey(
                key_hash=test_key_hash,
                name="rate-limit-test-key",
                role=ApiKeyRole.MEMBER,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    # Artificially fill rate limiter bucket to 50 requests
    import time

    friday_rate_limiter._history[test_key_hash] = [time.time()] * 50

    res_rate_limited = await friday_test_client.post(
        "/api/v1/friday/research",
        json={
            "friday_request_id": "req-rl-1",
            "question": "Rate limit check",
            "budget": {"max_sources": 5, "max_time_minutes": 5},
        },
        headers={"X-API-Key": "rate-limited-friday-key"},
    )
    assert res_rate_limited.status_code == 429
    assert "Retry-After" in res_rate_limited.headers
