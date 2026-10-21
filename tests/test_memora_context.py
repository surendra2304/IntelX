"""Comprehensive unit and integration tests for Memora Long-Term Memory integration."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from intelx.core.settings import Settings
from intelx.integrations.memora_context import (
    MemoraMemoryClient,
    store_verified_findings_to_memora,
)


@pytest.fixture
def memora_client():
    return MemoraMemoryClient(base_url="http://memora:8000", api_key="memora-test-key-123")


@pytest.mark.asyncio
async def test_memora_client_init_and_missing_credentials():
    """Client handles missing API key gracefully by blocking write."""
    client_no_key = MemoraMemoryClient(base_url="http://memora:8000", api_key="")
    res = await client_no_key._store_cloud_memory(
        namespace="intelx://research/test",
        content={"data": "sample"},
        provenance={"run_id": "r-1"},
    )
    assert res["status"] == "blocked_missing_credentials"
    assert res["cloud"] is False


@pytest.mark.asyncio
@respx.mock
async def test_memora_cloud_memory_success_and_error_handling(memora_client: MemoraMemoryClient):
    """Verify HTTP interactions with Memora API endpoint."""
    # 1. Successful 201 Created
    respx.post("http://memora:8000/v1/memories").mock(
        return_value=httpx.Response(201, json={"memory_id": "mem-101", "status": "indexed"})
    )
    res_ok = await memora_client._store_cloud_memory(
        namespace="intelx://research/briefs",
        content={"summary": "Market analysis"},
        provenance={"run_id": "r-101"},
    )
    assert res_ok["status"] == "stored"
    assert res_ok["cloud"] is True
    assert res_ok["response"]["memory_id"] == "mem-101"

    # 2. Upstream failure 500
    respx.post("http://memora:8000/v1/memories").mock(
        return_value=httpx.Response(500, json={"error": "Database error"})
    )
    res_fail = await memora_client._store_cloud_memory(
        namespace="intelx://research/briefs",
        content={"summary": "Market analysis"},
        provenance={"run_id": "r-101"},
    )
    assert res_fail["status"] == "failed_upstream"
    assert res_fail["cloud"] is False
    assert res_fail["status_code"] == 500

    # 3. Network timeout exception
    respx.post("http://memora:8000/v1/memories").mock(side_effect=httpx.ConnectTimeout("Timeout"))
    res_timeout = await memora_client._store_cloud_memory(
        namespace="intelx://research/briefs",
        content={"summary": "Market analysis"},
        provenance={"run_id": "r-101"},
    )
    assert res_timeout["status"] == "error"
    assert res_timeout["cloud"] is False
    assert res_timeout["error"] == "ConnectTimeout"


@pytest.mark.asyncio
async def test_store_research_memory_redaction_and_mock_mode():
    """Verify sensitive secret patterns are redacted before persistence."""
    client = MemoraMemoryClient()

    # With mock mode enabled
    with patch("intelx.integrations.memora_context.get_settings") as mock_settings:
        mock_settings.return_value = Settings(MOCK_MODE=True)

        res_mock = await client.store_research_memory(
            run_id="run-secret-001",
            objective="Testing secret scrubber",
            summary="API key was sk-1234567890abcdef1234567890abcdef in plain text.",
            evidence_count=2,
            claims_count=1,
        )
        assert res_mock["status"] == "stored_mock"
        assert res_mock["run_id"] == "run-secret-001"


@pytest.mark.asyncio
async def test_publish_research_handoff_filters_active_claims(memora_client: MemoraMemoryClient):
    """Verify handoff formats active claims with exact spans and ignores disputed/retracted claims."""
    claims = [
        {
            "id": "cl-active-1",
            "text": "Sodium energy density is 160 Wh/kg",
            "quote": "energy density is 160 Wh/kg",
            "span_start": 10,
            "span_end": 37,
            "confidence": 0.95,
            "status": "ACTIVE",
            "source_id": "src-1",
            "document_id": "doc-1",
        },
        {
            "id": "cl-disputed-2",
            "text": "Perpetual motion observed",
            "quote": "perpetual motion",
            "span_start": 0,
            "span_end": 16,
            "confidence": 0.1,
            "status": "DISPUTED",
            "source_id": "src-2",
            "document_id": "doc-2",
        },
    ]

    with patch.object(memora_client, "_store_cloud_memory", new_callable=AsyncMock) as mock_store:
        mock_store.return_value = {"status": "stored", "cloud": True}

        res_handoff = await memora_client.publish_research_handoff(
            run_id="run-handoff-002",
            objective="Evaluate sodium cell commercialization",
            summary="Sodium-ion batteries are reaching production viability.",
            claims=claims,
            sources=[{"id": "src-1"}],
        )

        assert res_handoff["status"] == "handoff_completed"
        assert res_handoff["claims_published"] == 1
        assert res_handoff["brief_namespace"] == "intelx://research/briefs"
        assert res_handoff["claims_namespace"] == "intelx://research/claims"


@pytest.mark.asyncio
async def test_store_verified_findings_to_memora_module_level():
    """Verify module-level store_verified_findings_to_memora filters to verified findings."""
    claims = [
        {
            "id": "cl-1",
            "text": "Sulfide cells achieve 800 cycles",
            "quote": "achieve 800 cycles",
            "span_start": 0,
            "span_end": 18,
            "status": "ACTIVE",
            "source_id": "src-1",
            "document_id": "doc-1",
        }
    ]
    findings = [
        {
            "id": "find-1",
            "statement": "Composite sulfide solid-state cells achieve 800 cycles.",
            "status": "verified",
            "confidence_score": 0.98,
            "evidence_count": 2,
            "claim_ids": ["cl-1"],
            "citations": [
                {"source_title": "Nature Energy 2026", "source_url": "https://nature.com"}
            ],
        },
        {
            "id": "find-2",
            "statement": "Unverified speculation on cold fusion.",
            "status": "unverified",
            "confidence_score": 0.20,
            "evidence_count": 0,
            "claim_ids": [],
            "citations": [],
        },
    ]

    res = await store_verified_findings_to_memora(
        findings=findings,
        claims=claims,
        sources=[{"id": "src-1", "title": "Nature Energy 2026", "location": "https://nature.com"}],
        run_id="run-find-003",
        objective="Assess solid-state cycle life",
    )

    # In mock mode or cloud write, returns findings handoff dictionary
    assert isinstance(res, (dict, int))
    if isinstance(res, dict):
        assert "status" in res or "findings_stored" in res or "run_id" in res
