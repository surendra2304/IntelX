"""End-to-End Integration Test for FRIDAY Autonomous Research Delegation and Lifecycle."""

import pytest
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.core.settings import get_settings
from intelx.db.session import get_sessionmaker
from intelx.orchestration.worker import OrchestrationWorker


@pytest.mark.asyncio
async def test_friday_delegation_pipeline_e2e(tmp_path):
    """Verify FRIDAY delegation -> Worker execution -> Findings with citations -> Report generation."""
    settings = get_settings()
    settings.MOCK_MODE = True
    settings.FRIDAY_API_KEY = "friday-e2e-secret-key"

    app = create_app()
    transport = ASGITransport(app=app)
    headers = {"X-API-Key": "friday-e2e-secret-key"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. FRIDAY delegates research question
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
        assert resp.status_code == 201
        data = resp.json()
        run_id = data["intelx_run_id"]
        assert data["friday_request_id"] == "friday-task-9001"
        assert data["status"].upper() == "QUEUED"
        assert data["subquestion_count"] >= 3

        # 2. In-process Orchestration Worker claims and executes the run
        worker = OrchestrationWorker()
        session_factory = get_sessionmaker()
        claimed_and_executed = await worker.run_once(session_factory)
        assert claimed_and_executed is True

        # 3. FRIDAY queries run status
        status_resp = await client.get(
            f"/api/v1/friday/research/{run_id}",
            headers=headers,
        )
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["status"].lower() in ("completed", "answered")
        assert status_data["current_phase"] == "completed"
        assert status_data["claims_count"] > 0
        assert status_data["findings_count"] > 0

        # 4. FRIDAY queries structured findings with resolved citations
        findings_resp = await client.get(
            f"/api/v1/friday/research/{run_id}/findings",
            headers=headers,
        )
        data_f = findings_resp.json()
        findings = data_f.get("findings", data_f) if isinstance(data_f, dict) else data_f
        assert len(findings) > 0
        for f in findings:
            assert "finding_id" in f
            assert "statement" in f
            assert "confidence_score" in f
            assert "citations" in f
            assert len(f["citations"]) > 0
            for cite in f["citations"]:
                assert "source_title" in cite
                assert "verbatim_span" in cite

        # 5. FRIDAY downloads full intelligence report
        report_resp = await client.get(
            f"/api/v1/friday/research/{run_id}/report",
            headers=headers,
        )
        assert report_resp.status_code == 200
        report_data = report_resp.json()
        assert "report_markdown" in report_data
        assert "report_json" in report_data
        md = report_data["report_markdown"]
        assert "Research Report" in md
        assert "Key Findings" in md
        assert "[C:" in md or "[S:" in md
