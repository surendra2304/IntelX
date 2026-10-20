"""Tests for Memora Research Handoff publishing under the intelx://research/ namespace."""

from types import SimpleNamespace

import pytest

from intelx.integrations import memora_context
from intelx.integrations.memora_context import MemoraMemoryClient


@pytest.mark.asyncio
async def test_publish_research_handoff_under_intelx_namespace(monkeypatch):
    """Verify research handoff publishes brief and claims under intelx://research/."""
    captured_posts = []

    class MockResponse:
        status_code = 201

        def json(self):
            return {"id": "mem-123"}

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, json, headers):
            captured_posts.append({"url": url, "payload": json, "headers": headers})
            return MockResponse()

    settings = SimpleNamespace(
        MEMORA_URL="http://memora:8000",
        INTELX_API_KEY="test-agent-key-32chars-minimum-length-req",
        MOCK_MODE=False,
    )
    monkeypatch.setattr(memora_context, "get_settings", lambda: settings)
    monkeypatch.setattr(memora_context.httpx, "AsyncClient", lambda **kwargs: MockAsyncClient())

    client = MemoraMemoryClient()
    claims = [
        {
            "id": "claim-1",
            "text": "Solid-state cell reached 450 Wh/kg.",
            "quote": "reached 450 Wh/kg",
            "span_start": 10,
            "span_end": 27,
            "confidence": 0.92,
            "status": "ACTIVE",
            "source_id": "src-1",
            "document_id": "doc-1",
        }
    ]
    findings = [
        {
            "statement": "Energy density of solid-state cells exceeds conventional lithium-ion.",
            "confidence": 0.90,
        }
    ]
    sources = [{"id": "src-1", "url": "https://nature.example/battery"}]

    result = await client.publish_research_handoff(
        run_id="run-handoff-99",
        objective="Assess solid-state battery density",
        summary="Verified findings show 450 Wh/kg achieved in lab trials.",
        claims=claims,
        findings=findings,
        sources=sources,
        namespace_prefix="intelx://research",
    )

    assert result["status"] == "handoff_completed"
    assert result["run_id"] == "run-handoff-99"
    assert result["claims_published"] == 1
    assert result["brief_namespace"] == "intelx://research/briefs"
    assert result["claims_namespace"] == "intelx://research/claims"

    # Verify captured POST requests
    assert len(captured_posts) == 2

    # Request 1: Brief
    brief_req = captured_posts[0]
    assert brief_req["url"] == "http://memora:8000/v1/memories"
    assert brief_req["payload"]["target_namespace_path"] == "intelx://research/briefs"
    assert brief_req["headers"]["X-Agent-Name"] == "intelx"

    # Request 2: Claims
    claims_req = captured_posts[1]
    assert claims_req["url"] == "http://memora:8000/v1/memories"
    assert claims_req["payload"]["target_namespace_path"] == "intelx://research/claims"
    assert "reached 450 Wh/kg" in claims_req["payload"]["content_text"]


@pytest.mark.asyncio
async def test_publish_research_handoff_mock_mode():
    """Verify research handoff in mock mode stores synthetic records without network calls."""
    client = MemoraMemoryClient()
    claims = [
        {
            "id": "claim-mock-1",
            "text": "Synthetic biology yield increased 3x.",
            "quote": "yield increased 3x",
            "span_start": 0,
            "span_end": 18,
            "confidence": 0.88,
            "status": "ACTIVE",
        }
    ]

    result = await client.publish_research_handoff(
        run_id="run-mock-1",
        objective="Analyze yield improvement",
        summary="Yield verified 3x over baseline.",
        claims=claims,
        namespace_prefix="intelx://research",
    )

    assert result["status"] == "handoff_completed"
    assert result["brief"]["status"] == "stored_mock"
    assert result["claims"]["status"] == "stored_mock"
    assert result["brief_namespace"] == "intelx://research/briefs"
    assert result["claims_namespace"] == "intelx://research/claims"
