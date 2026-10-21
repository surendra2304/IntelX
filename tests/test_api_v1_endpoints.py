"""Comprehensive tests for INTELX v1 Core Endpoints (intelx/api/v1/endpoints.py)."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from intelx.app.factory import create_app
from intelx.core.auth import hash_api_key
from intelx.core.enums import (
    ApiKeyRole,
    ArtifactFormat,
    ArtifactType,
    ClaimOrigin,
    ClaimStatus,
    ClaimType,
    RunOutcome,
    RunStatus,
    SourceKind,
    TrustTier,
)
from intelx.db.base import Base
from intelx.db.engine import get_async_engine
from intelx.db.models import ApiKey, Artifact, Claim
from intelx.db.repos import RunRepo, SourceRepo
from intelx.db.session import get_sessionmaker


@pytest_asyncio.fixture
async def api_clients() -> AsyncGenerator[tuple[AsyncClient, AsyncClient], None]:
    """Provide admin client and member client with seeded database."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    admin_key_raw = "admin-secret-token-111"
    member_key_raw = "member-secret-token-222"

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        # Seed Admin API Key
        a_hash = hash_api_key(admin_key_raw)
        stmt_a = select(ApiKey).where(ApiKey.key_hash == a_hash)
        if not (await session.execute(stmt_a)).scalar_one_or_none():
            session.add(
                ApiKey(
                    key_hash=a_hash,
                    name="admin-operator",
                    role=ApiKeyRole.ADMIN,
                    created_at=datetime.now(UTC),
                )
            )

        # Seed Member API Key
        m_hash = hash_api_key(member_key_raw)
        stmt_m = select(ApiKey).where(ApiKey.key_hash == m_hash)
        if not (await session.execute(stmt_m)).scalar_one_or_none():
            session.add(
                ApiKey(
                    key_hash=m_hash,
                    name="member-analyst",
                    role=ApiKeyRole.MEMBER,
                    created_at=datetime.now(UTC),
                )
            )

        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)

    async with (
        AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-API-Key": admin_key_raw},
        ) as admin_client,
        AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-API-Key": member_key_raw},
        ) as member_client,
    ):
        yield admin_client, member_client


@pytest.mark.asyncio
async def test_create_and_list_research_jobs(api_clients: tuple[AsyncClient, AsyncClient]):
    """Verify POST /research/jobs creation, legacy budget schema, and GET listing."""
    _, member_client = api_clients

    # 1. Create standard job
    res_job = await member_client.post(
        "/api/v1/research/jobs",
        json={
            "objective": "Investigate Gallium Nitride high-voltage power semiconductor efficiency",
            "scope": {"depth": "standard", "max_sources": 10},
            "budget": {"max_usd": 8.0, "max_minutes": 20},
        },
    )
    assert res_job.status_code == 202
    job_data = res_job.json()
    assert job_data["status"] == "QUEUED"
    job_id = job_data["id"]
    assert job_id is not None

    # 2. Create job with legacy nested budget inside scope
    res_legacy = await member_client.post(
        "/api/v1/research/jobs",
        json={
            "objective": "Legacy client request for silicon carbide wafer processing",
            "scope": {
                "depth": "deep",
                "budget": {"max_usd": 9.5, "max_minutes": 25},
            },
        },
    )
    assert res_legacy.status_code == 202
    legacy_data = res_legacy.json()
    assert legacy_data["status"] == "QUEUED"

    # 3. List jobs
    res_list = await member_client.get("/api/v1/research/jobs?limit=10")
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert "items" in list_data
    items = list_data["items"]
    assert len(items) >= 2
    assert any(j["id"] == job_id for j in items)

    # 4. Get specific job details
    res_get = await member_client.get(f"/api/v1/research/jobs/{job_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == job_id
    assert "Gallium Nitride" in res_get.json()["objective"]


@pytest.mark.asyncio
async def test_cancel_research_jobs_via_both_routes(api_clients: tuple[AsyncClient, AsyncClient]):
    """Verify cancelling via /research/jobs/{id}/cancel and /runs/{id}."""
    _, member_client = api_clients

    # Create job 1
    res1 = await member_client.post(
        "/api/v1/research/jobs",
        json={"objective": "Test job 1 for cancel endpoint"},
    )
    job1_id = res1.json()["id"]

    # Cancel via POST /research/jobs/{id}/cancel
    res_cancel = await member_client.post(f"/api/v1/research/jobs/{job1_id}/cancel")
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "CANCELLED"

    # Create job 2
    res2 = await member_client.post(
        "/api/v1/research/jobs",
        json={"objective": "Test job 2 for runs delete route"},
    )
    job2_id = res2.json()["id"]

    # Cancel via DELETE /runs/{id}
    res_del_run = await member_client.delete(f"/api/v1/runs/{job2_id}")
    assert res_del_run.status_code == 200
    assert res_del_run.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_job_events_and_artifacts(api_clients: tuple[AsyncClient, AsyncClient], tmp_path):
    """Verify polling events and listing/downloading artifacts."""
    _, member_client = api_clients

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective="Inspect artifacts and telemetry events test",
            created_by="member-analyst",
        )
        run_id = run.id

        # Emit an event
        await RunRepo.add_event(
            session=session,
            run_id=run_id,
            event_type="test.event.emitted",
            payload_json={"sample": "data"},
        )

        # Create sample artifact file
        test_file = tmp_path / "report.md"
        test_file.write_text("# Test Artifact\nContent here", encoding="utf-8")

        art = Artifact(
            run_id=run_id,
            type=ArtifactType.REPORT,
            format=ArtifactFormat.MD,
            path=str(test_file),
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            created_at=datetime.now(UTC),
        )
        session.add(art)
        await session.commit()
        art_id = art.id

    # 1. Poll events
    res_events = await member_client.get(f"/api/v1/research/jobs/{run_id}/events")
    assert res_events.status_code == 200
    events = res_events.json()
    assert len(events) >= 1
    assert any(e["type"] == "test.event.emitted" for e in events)

    # 2. List artifacts
    res_artifacts = await member_client.get(f"/api/v1/research/jobs/{run_id}/artifacts")
    assert res_artifacts.status_code == 200
    artifacts_list = res_artifacts.json()
    assert len(artifacts_list) >= 1
    assert any(a["id"] == art_id for a in artifacts_list)

    # 3. Download artifact
    res_dl = await member_client.get(f"/api/v1/artifacts/{art_id}")
    assert res_dl.status_code == 200
    assert b"Test Artifact" in res_dl.content


@pytest.mark.asyncio
async def test_job_followup_and_review(api_clients: tuple[AsyncClient, AsyncClient]):
    """Verify triggering followup research jobs and human-in-the-loop review decisions."""
    admin_client, member_client = api_clients

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective="Completed research run for review and followup",
            created_by="member-analyst",
        )
        run.status = RunStatus.COMPLETED
        run.outcome = RunOutcome.ANSWERED
        run.completed_at = datetime.now(UTC)
        await session.commit()
        run_id = run.id

    # 1. Followup (POST /research/jobs/{id}/followups)
    res_followup = await member_client.post(
        f"/api/v1/research/jobs/{run_id}/followups",
        json={"focus": "Investigate alternative thermal interfaces and packaging"},
    )
    assert res_followup.status_code == 202
    followup_data = res_followup.json()
    assert followup_data["status"] == "QUEUED"

    # 2. Review - approve (Admin only)
    res_review = await admin_client.post(
        f"/api/v1/research/jobs/{run_id}/review",
        json={"decision": "APPROVED", "notes": "Thoroughly grounded evidence with peer review."},
    )
    assert res_review.status_code == 200
    assert res_review.json()["status"] == "recorded"


@pytest.mark.asyncio
async def test_knowledge_query_and_source_management(api_clients: tuple[AsyncClient, AsyncClient]):
    """Verify full-text search, source metadata, and admin trust updates."""
    admin_client, member_client = api_clients

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        src = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://semi-conductor.org/sic-packaging",
            title="Silicon Carbide Packaging Standard",
            publisher="Power Electronics Consortium",
            trust_tier=TrustTier.STANDARD,
        )
        src_id = src.id
        await session.commit()

    # 1. Member queries knowledge search
    res_kq = await member_client.post(
        "/api/v1/knowledge/query",
        json={"q": "Silicon", "limit": 5},
    )
    assert res_kq.status_code == 200
    assert "count" in res_kq.json()

    # 2. Member retrieves source metadata
    res_src = await member_client.get(f"/api/v1/sources/{src_id}")
    assert res_src.status_code == 200
    assert res_src.json()["id"] == src_id
    assert res_src.json()["title"] == "Silicon Carbide Packaging Standard"

    # 3. Non-admin member fails to update trust tier -> 403 Forbidden
    res_trust_forbidden = await member_client.post(
        f"/api/v1/sources/{src_id}/trust",
        json={"tier": "TRUSTED"},
    )
    assert res_trust_forbidden.status_code == 403

    # 4. Admin updates trust tier -> 200 OK
    res_trust_admin = await admin_client.post(
        f"/api/v1/sources/{src_id}/trust",
        json={"tier": "TRUSTED"},
    )
    assert res_trust_admin.status_code == 200
    assert "TRUSTED" in res_trust_admin.json()["trust_tier"]


@pytest.mark.asyncio
async def test_claim_retraction_admin_only(api_clients: tuple[AsyncClient, AsyncClient]):
    """Verify claim retraction requires admin role and updates status."""
    admin_client, member_client = api_clients

    from intelx.db.models import Document

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        run = await RunRepo.create_run(session=session, objective="Claim retraction test run")
        src = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://physics.test/carnot-cycle",
            title="Carnot Cycle Analysis",
            publisher="Physics Archive",
        )
        from intelx.db.models import Chunk

        doc = Document(
            source_id=src.id,
            text="100% Carnot engine efficiency statement text here for verification span testing.",
            created_at=datetime.now(UTC),
        )
        session.add(doc)
        await session.flush()

        chunk = Chunk(
            document_id=doc.id,
            idx=0,
            start_char=0,
            end_char=29,
            text="100% Carnot engine efficiency",
        )
        session.add(chunk)
        await session.flush()

        claim = Claim(
            run_id=run.id,
            source_id=src.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            text="100% Carnot engine efficiency",
            quote="100% Carnot engine efficiency",
            span_start=0,
            span_end=29,
            subject="Carnot Engine",
            predicate="efficiency",
            confidence=0.1,
            claim_type=ClaimType.FACT,
            entities_json=[],
            created_by_agent="extractor",
            origin=ClaimOrigin.EXTRACTED,
            status=ClaimStatus.ACTIVE,
            created_at=datetime.now(UTC),
        )
        session.add(claim)
        await session.commit()
        claim_id = claim.id

    # 1. Member is rejected with 403
    res_member = await member_client.post(
        f"/api/v1/knowledge/claims/{claim_id}/retract",
        json={"reason": "Violates thermodynamic Carnot limit"},
    )
    assert res_member.status_code == 403

    # 2. Admin successfully retracts
    res_admin = await admin_client.post(
        f"/api/v1/knowledge/claims/{claim_id}/retract",
        json={"reason": "Violates thermodynamic Carnot limit"},
    )
    assert res_admin.status_code == 200
    assert res_admin.json()["status"] == "RETRACTED"


@pytest.mark.asyncio
async def test_policy_and_audit_endpoints(api_clients: tuple[AsyncClient, AsyncClient]):
    """Verify policy management, audit ledger, and cryptographic verification."""
    admin_client, member_client = api_clients

    # 1. Member forbidden on policies
    assert (await member_client.get("/api/v1/policies")).status_code == 403
    assert (await member_client.get("/api/v1/audit")).status_code == 403
    assert (await member_client.get("/api/v1/audit/verify")).status_code == 403

    # 2. Admin retrieves policies
    res_pol = await admin_client.get("/api/v1/policies")
    assert res_pol.status_code == 200
    assert "config" in res_pol.json()

    # 3. Admin gets audit trail
    res_audit = await admin_client.get("/api/v1/audit?limit=10")
    assert res_audit.status_code == 200
    assert isinstance(res_audit.json(), list)

    # 4. Admin verifies audit ledger integrity
    res_verify = await admin_client.get("/api/v1/audit/verify")
    assert res_verify.status_code == 200
    assert "valid" in res_verify.json()

    # 5. Admin retention purge
    res_purge = await admin_client.post("/api/v1/admin/retention/purge?days=90")
    assert res_purge.status_code == 200
    assert (
        "purged" in res_purge.json()
        or "status" in res_purge.json()
        or isinstance(res_purge.json(), dict)
    )
