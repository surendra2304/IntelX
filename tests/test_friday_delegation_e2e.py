"""End-to-End Integration Test for FRIDAY Autonomous Research Delegation and Lifecycle."""

import pytest
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.core.auth import seed_api_keys_from_settings
from intelx.core.settings import get_settings
from intelx.db.session import get_sessionmaker
from intelx.orchestration.worker import OrchestrationWorker


@pytest.mark.asyncio
async def test_friday_delegation_pipeline_e2e(tmp_path):
    """Verify FRIDAY delegation -> Worker execution -> Findings with citations -> Report generation."""
    settings = get_settings()
    settings.MOCK_MODE = True
    settings.FRIDAY_API_KEY = "friday-e2e-secret-key"
    async with get_sessionmaker()() as session:
        await seed_api_keys_from_settings(session, settings)

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

        # Ownership must use the API key principal identity because the universal
        # task cancellation route applies exactly that object-level authorization.
        from intelx.db.repos import RunRepo

        async with get_sessionmaker()() as session:
            delegated_run = await RunRepo.get_run(session, run_id)
            assert delegated_run is not None
            assert delegated_run.created_by == "friday-delegation"
            assert delegated_run.scope_json["context"]["requesting_system"] == "sentinel"
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
        # A benchmark question must retain its unit-bearing value even though the
        # objective does not repeat the metric name verbatim.
        assert "160 Wh/kg" in md

        # End-to-end task-level check: a comparison objective with two explicitly
        # disputed measurements must report the conflict status, not generic consensus.
        conflict_payload = dict(delegation_payload)
        conflict_payload["friday_request_id"] = "friday-task-conflict-9003"
        conflict_payload["question"] = (
            "Investigate silicon composite anode energy density benchmarks and limits"
        )
        conflict_resp = await client.post(
            "/api/v1/friday/research", json=conflict_payload, headers=headers
        )
        assert conflict_resp.status_code == 201
        conflict_run_id = conflict_resp.json()["intelx_run_id"]
        assert await worker.run_once(session_factory) is True
        conflict_report_resp = await client.get(
            f"/api/v1/friday/research/{conflict_run_id}/report", headers=headers
        )
        assert conflict_report_resp.status_code == 200
        conflict_report = conflict_report_resp.json()["report_markdown"]
        assert "DISPUTED" in conflict_report
        assert "detected evidence conflict" in conflict_report

        # A delegated principal must be able to cancel its own queued work through
        # the universal task protocol, while the same route denies other owners.
        cancel_payload = dict(delegation_payload)
        cancel_payload["friday_request_id"] = "friday-task-cancel-9002"
        cancel_resp = await client.post(
            "/api/v1/friday/research", json=cancel_payload, headers=headers
        )
        assert cancel_resp.status_code == 201
        cancel_run_id = cancel_resp.json()["intelx_run_id"]
        universal_cancel = await client.post(
            "/v1/task/execute",
            json={"action": "cancel", "payload": {"run_id": cancel_run_id}},
            headers=headers,
        )
        assert universal_cancel.status_code == 200
        assert universal_cancel.json()["status"] == "CANCELLED"
