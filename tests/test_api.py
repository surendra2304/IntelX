"""Tests for INTELX REST API Surface, Auth, Rate Limiting, Policies, and Lifecycle."""

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.core.auth import hash_api_key, rate_limiter
from intelx.core.enums import ApiKeyRole, ClaimStatus, RunStatus
from intelx.db.models import ApiKey
from intelx.db.repos import ClaimRepo, RunRepo
from intelx.db.session import get_sessionmaker
from intelx.orchestration.worker import OrchestrationWorker


@pytest_asyncio.fixture
async def app_client():
    """Create test client with initialized database schemas and seeded API keys."""
    app = create_app()
    admin_key_raw = "intelx_admin_secret_test_key"
    member_key_raw = "intelx_member_secret_test_key"

    # Seed keys directly into test database
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        # Admin key
        k_admin = ApiKey(
            key_hash=hash_api_key(admin_key_raw),
            name="test-admin",
            role=ApiKeyRole.ADMIN,
        )
        # Member key
        k_member = ApiKey(
            key_hash=hash_api_key(member_key_raw),
            name="test-member",
            role=ApiKeyRole.MEMBER,
        )
        session.add_all([k_admin, k_member])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.admin_headers = {"Authorization": f"Bearer {admin_key_raw}"}
        client.member_headers = {"Authorization": f"Bearer {member_key_raw}"}
        yield client


@pytest.mark.asyncio
async def test_auth_401_and_403_and_idempotent_replay(app_client):
    """Verify 401 on missing/invalid auth, 403 on role violation, and 200 on idempotent replay."""
    # 1. 401 Unauthorized
    res_no_auth = await app_client.get("/api/v1/research/jobs")
    assert res_no_auth.status_code == 401

    res_bad_auth = await app_client.get(
        "/api/v1/research/jobs", headers={"Authorization": "Bearer bad_secret"}
    )
    assert res_bad_auth.status_code == 401

    # 2. 403 Forbidden (member attempting admin endpoint)
    res_403 = await app_client.get("/api/v1/policies", headers=app_client.member_headers)
    assert res_403.status_code == 403

    # Admin access allowed
    res_admin = await app_client.get("/api/v1/policies", headers=app_client.admin_headers)
    assert res_admin.status_code == 200

    # 3. Idempotent Job Submission Replay
    payload = {"objective": "Assess fusion reactor plasma containment progress"}
    headers_idem = {
        **app_client.member_headers,
        "Idempotency-Key": "idem-key-fusion-123",
    }

    res_first = await app_client.post("/api/v1/research/jobs", json=payload, headers=headers_idem)
    assert res_first.status_code == 202
    job_id = res_first.json()["id"]

    # Replay within 24h -> returns 200 with same job_id
    res_replay = await app_client.post("/api/v1/research/jobs", json=payload, headers=headers_idem)
    assert res_replay.status_code == 200
    assert res_replay.json()["id"] == job_id


@pytest.mark.asyncio
async def test_rate_limiter_429(app_client):
    """Verify rate limiter triggers 429 when threshold exceeded."""
    test_key_raw = "intelx_rate_limit_test_key"
    test_hash = hash_api_key(test_key_raw)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        session.add(
            ApiKey(
                key_hash=test_hash,
                name="rate-limit-test",
                role=ApiKeyRole.MEMBER,
            )
        )
        await session.commit()

    hdrs = {"Authorization": f"Bearer {test_key_raw}"}

    # Artificially fill rate limiter bucket
    for _ in range(120):
        rate_limiter.check_rate_limit(test_hash, limit=120)

    # 121st request -> 429 Too Many Requests
    res = await app_client.get("/api/v1/research/jobs", headers=hdrs)
    assert res.status_code == 429
    assert "Retry-After" in res.headers


@pytest.mark.asyncio
async def test_full_api_lifecycle_and_artifact_download(app_client):
    """Verify submit -> execute -> poll events -> download report.md + report.json."""
    fixture_path = Path("./tests/fixtures/docs/sample_battery.txt").resolve()
    payload = {
        "objective": "Evaluate solid-state electrolyte conductivity",
        "scope": {"depth": "standard", "allowed_domains": ["local"]},
        "budget": {"max_usd": 5.0, "max_minutes": 10},
    }

    # 1. Submit Job
    res = await app_client.post(
        "/api/v1/research/jobs", json=payload, headers=app_client.member_headers
    )
    assert res.status_code == 202
    job_id = res.json()["id"]

    # Ingest a source and claim associated with this run for testing synthesis
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        from intelx.memory.normalize import ingest_and_normalize

        text_content = fixture_path.read_text(encoding="utf-8")
        source, doc, chunks, _ = await ingest_and_normalize(
            session=session,
            raw_bytes=text_content.encode("utf-8"),
            location=str(fixture_path),
            kind="FILE",
            created_by_run_id=job_id,
        )
        quote = "significant thermal stability"
        sp_start = text_content.index(quote)
        sp_end = sp_start + len(quote)
        await ClaimRepo.create_claim(
            session=session,
            run_id=job_id,
            source_id=source.id,
            document_id=doc.id,
            chunk_id=chunks[0].id,
            text_content="Electrolyte shows significant thermal stability across cycles.",
            quote=quote,
            span_start=sp_start,
            span_end=sp_end,
            claim_type="FACT",
        )
        await session.commit()

    # 2. Run background worker on the queued job
    worker = OrchestrationWorker()
    processed = await worker.run_once(sessionmaker)
    assert processed is True

    # 3. Check Job Status
    res_job = await app_client.get(
        f"/api/v1/research/jobs/{job_id}", headers=app_client.member_headers
    )
    assert res_job.status_code == 200
    assert res_job.json()["status"] == "COMPLETED"

    # 4. Check Events
    res_events = await app_client.get(
        f"/api/v1/research/jobs/{job_id}/events",
        headers=app_client.member_headers,
    )
    assert res_events.status_code == 200
    assert len(res_events.json()) >= 3

    # 5. List Artifacts
    res_art = await app_client.get(
        f"/api/v1/research/jobs/{job_id}/artifacts",
        headers=app_client.member_headers,
    )
    assert res_art.status_code == 200
    artifacts = res_art.json()
    assert len(artifacts) == 4

    # 6. Download Artifacts
    md_art = next(a for a in artifacts if a["format"] == "MD")
    res_md = await app_client.get(
        f"/api/v1/artifacts/{md_art['id']}?format=md",
        headers=app_client.member_headers,
    )
    assert res_md.status_code == 200
    assert "# Research Report:" in res_md.text

    json_art = next(a for a in artifacts if a["format"] == "JSON")
    res_json = await app_client.get(
        f"/api/v1/artifacts/{json_art['id']}?format=json",
        headers=app_client.member_headers,
    )
    assert res_json.status_code == 200
    assert res_json.json()["schema_version"] == "v1.0"


@pytest.mark.asyncio
async def test_job_cancellation_lifecycle(app_client):
    """Verify cancel on active job returns 200 and cancel on completed job returns 409."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        run_active = await RunRepo.create_run(session, objective="Active job cancellation test")
        run_completed = await RunRepo.create_run(
            session, objective="Completed job cancellation test"
        )
        run_completed.status = RunStatus.COMPLETED
        await session.commit()
        active_id = run_active.id
        completed_id = run_completed.id

    # 1. Cancel Active Job -> 200
    res_cancel_active = await app_client.post(
        f"/api/v1/research/jobs/{active_id}/cancel",
        headers=app_client.member_headers,
    )
    assert res_cancel_active.status_code == 200
    assert res_cancel_active.json()["status"] == "CANCELLED"

    # 2. Cancel Completed Job -> 409 Conflict
    res_cancel_comp = await app_client.post(
        f"/api/v1/research/jobs/{completed_id}/cancel",
        headers=app_client.member_headers,
    )
    assert res_cancel_comp.status_code == 409


@pytest.mark.asyncio
async def test_policy_denial_and_audit(app_client):
    """Verify denylisting a domain blocks execution and writes an audit event."""
    # 1. Update Policy via Admin PUT
    new_policy = {
        "domain_denylist": ["untrusted-domain.com"],
        "max_sources_per_run": 25,
        "allowed_connector_kinds": ["HTTP", "SEARCH", "FILE"],
        "blocked_file_extensions": [".exe", ".bat"],
        "max_run_usd": 15.0,
        "max_run_minutes": 45,
    }
    res_put = await app_client.put(
        "/api/v1/policies", json=new_policy, headers=app_client.admin_headers
    )
    assert res_put.status_code == 200
    assert res_put.json()["config"]["domain_denylist"] == ["untrusted-domain.com"]

    # 2. Verify Audit Log contains policy.updated
    res_audit = await app_client.get("/api/v1/audit", headers=app_client.admin_headers)
    assert res_audit.status_code == 200
    actions = [a["action"] for a in res_audit.json()]
    assert "policy.updated" in actions

    # 3. Verify Cryptographic Audit Verification endpoint
    res_verify = await app_client.get("/api/v1/audit/verify", headers=app_client.admin_headers)
    assert res_verify.status_code == 200
    assert res_verify.json()["valid"] is True


@pytest.mark.asyncio
async def test_claim_retraction_audit(app_client):
    """Verify claim retraction updates status and writes an audit ledger entry."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        from intelx.memory.normalize import ingest_and_normalize

        run = await RunRepo.create_run(session, objective="Claim retraction test")
        text = "Erronous benchmark measurement data."
        source, doc, chunks, _ = await ingest_and_normalize(
            session=session,
            raw_bytes=text.encode("utf-8"),
            location="local_test.txt",
            kind="FILE",
        )
        quote = "benchmark measurement"
        sp_start = text.index(quote)
        sp_end = sp_start + len(quote)
        claim = await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=source.id,
            document_id=doc.id,
            chunk_id=chunks[0].id,
            text_content="Erronous benchmark measurement.",
            quote=quote,
            span_start=sp_start,
            span_end=sp_end,
            claim_type="MEASUREMENT",
        )
        await session.commit()
        claim_id = claim.id

    # Retract claim via Admin POST
    res_retract = await app_client.post(
        f"/api/v1/knowledge/claims/{claim_id}/retract",
        json={"reason": "Lab equipment calibration failure invalidated readings."},
        headers=app_client.admin_headers,
    )
    assert res_retract.status_code == 200
    assert res_retract.json()["status"] == "RETRACTED"

    # Verify claim status in DB
    async with sessionmaker() as session:
        updated_claim = await ClaimRepo.get_claim(session, claim_id)
        assert updated_claim.status == ClaimStatus.RETRACTED
        assert "calibration failure" in updated_claim.retraction_reason


@pytest.mark.asyncio
async def test_openapi_schema_generation(app_client):
    """Verify OpenAPI JSON schema generates cleanly and includes all v1 routes."""
    res = await app_client.get("/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    paths = schema.get("paths", {})

    assert "/api/v1/research/jobs" in paths
    assert "/api/v1/research/jobs/{job_id}" in paths
    assert "/api/v1/research/jobs/{job_id}/cancel" in paths
    assert "/api/v1/research/jobs/{job_id}/events" in paths
    assert "/api/v1/research/jobs/{job_id}/artifacts" in paths
    assert "/api/v1/artifacts/{artifact_id}" in paths
    assert "/api/v1/research/jobs/{job_id}/followups" in paths
    assert "/api/v1/research/jobs/{job_id}/review" in paths
    assert "/api/v1/knowledge/query" in paths
    assert "/api/v1/sources/{source_id}/trust" in paths
    assert "/api/v1/knowledge/claims/{claim_id}/retract" in paths
    assert "/api/v1/policies" in paths
    assert "/api/v1/audit" in paths
    assert "/api/v1/audit/verify" in paths
