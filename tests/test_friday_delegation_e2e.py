"""End-to-End Integration Test for FRIDAY Autonomous Research Delegation and Lifecycle.

This test verifies the mesh-dispatch-style synchronous research execution path,
which queries existing completed runs and returns synthesized findings immediately
(instead of the old async pipeline that created runs and required worker execution).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.core.auth import seed_api_keys_from_settings
from intelx.core.settings import get_settings
from intelx.db.session import get_sessionmaker


@pytest.mark.asyncio
async def test_friday_delegation_pipeline_e2e(tmp_path):
    """Verify FRIDAY delegation -> Mesh dispatch path -> Synthesized findings with citations."""
    from intelx.db.base import Base
    from intelx.db.engine import get_async_engine

    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = get_settings()
    settings.MOCK_MODE = True
    settings.FRIDAY_API_KEY = "friday-e2e-secret-key"
    async with get_sessionmaker()() as session:
        await seed_api_keys_from_settings(session, settings)

    app = create_app()
    transport = ASGITransport(app=app)
    headers = {"X-API-Key": "friday-e2e-secret-key"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. FRIDAY delegates research question - returns findings directly (mesh dispatch path)
        delegation_payload = {
            "friday_request_id": "friday-task-9001",
            "question": "Assess sodium-ion battery cathode energy density and thermal stability benchmarks",
            "context": {
                "requesting_system": "sentinel",
                "priority": "urgent",
                "domain_hint": "security",
            },
            "depth": "standard",
            "budget": {
                "max_sources": 5,
                "max_time_minutes": 10,
            },
        }

        resp = await client.post(
            "/api/v1/friday/research",
            json=delegation_payload,
            headers=headers,
        )
        # Now returns 200 OK with findings directly (synchronous mesh dispatch path)
        assert resp.status_code == 200
        data = resp.json()
        run_id = data["run_id"]
        assert data["friday_request_id"] == "friday-task-9001"
        assert data["status"] == "SUCCESS"
        assert "findings" in data
        assert "citations" in data
        assert "spoken_summary" in data
        assert "sources" in data
        assert "provenance_chain" in data
        assert "text_response" in data
        assert data["query"] == delegation_payload["question"]
        assert "execution_time_ms" in data

        # 2. Verify findings structure matches mesh dispatch response
        findings = data["findings"]
        assert isinstance(findings, list)
        # In MOCK_MODE with empty DB, findings may be empty but structure should be valid
        for f in findings:
            assert "finding_id" in f
            assert "statement" in f
            assert "confidence_score" in f
            assert "evidence_count" in f
            assert "citations" in f
            assert "status" in f
            assert "claim_ids" in f
            for cite in f["citations"]:
                assert "source_id" in cite
                assert "source_title" in cite
                assert "source_url" in cite

        # 3. Verify citations/sources structure
        citations = data["citations"]
        sources = data["sources"]
        assert isinstance(citations, list)
        assert isinstance(sources, list)
        assert citations == sources  # citations and sources are the same data
        for src in sources:
            assert "id" in src
            assert "title" in src
            assert "url" in src
            assert "publisher" in src
            assert "trust_tier" in src

        # 4. Verify spoken_summary and text_response are present
        assert isinstance(data["spoken_summary"], str)
        assert isinstance(data["text_response"], str)

        # 5. Verify provenance_chain structure
        provenance = data["provenance_chain"]
        assert isinstance(provenance, list)
        for prov in provenance:
            assert "claim_id" in prov
            assert "claim_text" in prov
            assert "quote" in prov
            assert "source_id" in prov
            assert "source_title" in prov
            assert "source_url" in prov

        # 6. Test idempotency - same friday_request_id should return same run_id
        resp2 = await client.post(
            "/api/v1/friday/research",
            json=delegation_payload,
            headers=headers,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["run_id"] == run_id  # Same run_id for idempotent request
        assert data2["friday_request_id"] == "friday-task-9001"

        # 7. Test cancellation action
        cancel_payload = dict(delegation_payload)
        cancel_payload["friday_request_id"] = "friday-task-cancel-9002"
        cancel_payload["action"] = "cancel"
        cancel_payload["run_id"] = run_id
        cancel_resp = await client.post(
            "/api/v1/friday/research", json=cancel_payload, headers=headers
        )
        assert cancel_resp.status_code == 200
        cancel_data = cancel_resp.json()
        assert cancel_data["run_id"] == run_id
        assert cancel_data["status"] == "CANCELLED"
        assert "message" in cancel_data

        # 8. Test /delegate alias endpoint
        delegate_payload = dict(delegation_payload)
        delegate_payload["friday_request_id"] = "friday-task-delegate-9003"
        delegate_resp = await client.post(
            "/api/v1/friday/delegate", json=delegate_payload, headers=headers
        )
        assert delegate_resp.status_code == 200
        delegate_data = delegate_resp.json()
        assert "run_id" in delegate_data
        assert delegate_data["status"] == "SUCCESS"
        assert delegate_data["friday_request_id"] == "friday-task-delegate-9003"
