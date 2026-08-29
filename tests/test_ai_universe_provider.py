"""Tests for AI-Universe Multi-Agent Intelligence Provider Integration and Fallback Chain."""

import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from intelx.core.confidence import compute_confidence_score
from intelx.core.settings import Settings
from intelx.models.ai_universe_provider import AI_UNIVERSE_ROLE_MAP, AIUniverseProvider
from intelx.models.gateway import ModelGateway


class DummySchema(BaseModel):
    summary: str
    confidence: float


def test_ai_universe_role_persona_mappings():
    """Verify exact role-to-persona mapping matching the architectural contract."""
    assert AI_UNIVERSE_ROLE_MAP["planner"] == "Strategist"
    assert AI_UNIVERSE_ROLE_MAP["extractor"] == "Coder"
    assert AI_UNIVERSE_ROLE_MAP["verifier"] == "Fact Checker + Critic"
    assert AI_UNIVERSE_ROLE_MAP["analyst"] == "Data Analyst"
    assert AI_UNIVERSE_ROLE_MAP["critic"] == "Critic"
    assert AI_UNIVERSE_ROLE_MAP["synthesizer"] == "Synthesizer"


@pytest.mark.asyncio
@respx.mock
async def test_ai_universe_provider_successful_completion():
    """Verify AIUniverseProvider sends request and receives structured multi-agent response."""
    endpoint_url = "http://localhost:9000/v1/intelx/research"
    mock_response = {
        "response": json.dumps({"summary": "Debated and verified claim.", "confidence": 0.95}),
        "confidence": 0.95,
        "key_evidence_used": ["doc-1#span(0,40)"],
        "dissent": "No dissenting opinion among Fact Checker and Critic agents.",
        "provenance": {
            "agent_personas": ["Fact Checker", "Critic"],
            "model": "ai-universe-multi-agent",
            "latency_ms": 110,
        },
    }

    respx.post(endpoint_url).mock(return_value=httpx.Response(200, json=mock_response))

    provider = AIUniverseProvider(base_url="http://localhost:9000", api_key="aiu-secret-key")
    messages = [{"role": "user", "content": "Verify claim regarding quantum coherence time."}]

    text, usage = await provider.complete(
        messages=messages,
        model="ai-universe-v1",
        role="verifier",
        schema_model=DummySchema,
    )

    assert text is not None
    data = json.loads(text)
    assert data["summary"] == "Debated and verified claim."
    assert provider.last_metadata["role"] == "verifier"
    assert provider.last_metadata["persona"] == "Fact Checker + Critic"
    assert provider.last_metadata["confidence"] == 0.95
    assert usage.input_tokens > 0


@pytest.mark.asyncio
@respx.mock
async def test_ai_universe_provider_endpoint_fallback():
    """Verify provider falls back to /intelx/research if /v1/intelx/research returns 404."""
    v1_url = "http://localhost:9000/v1/intelx/research"
    alt_url = "http://localhost:9000/intelx/research"

    respx.post(v1_url).mock(return_value=httpx.Response(404))
    respx.post(alt_url).mock(
        return_value=httpx.Response(
            200, json={"response": "Fallback path success", "confidence": 0.88}
        )
    )

    provider = AIUniverseProvider(base_url="http://localhost:9000")
    text, _ = await provider.complete(
        messages=[{"role": "user", "content": "Test fallback"}],
        model="ai-universe-v1",
        role="planner",
    )
    assert text == "Fallback path success"


@pytest.mark.asyncio
@respx.mock
async def test_gateway_fallback_chain_from_ai_universe_to_mock():
    """Verify ModelGateway falls back gracefully to MockProvider when AI-Universe is offline."""
    v1_url = "http://localhost:9000/v1/intelx/research"
    alt_url = "http://localhost:9000/intelx/research"

    # Simulate connection failure to AI-Universe
    respx.post(v1_url).mock(side_effect=httpx.ConnectError("Connection refused"))
    respx.post(alt_url).mock(side_effect=httpx.ConnectError("Connection refused"))

    custom_settings = Settings(
        MOCK_MODE=False,
        LLM_PROVIDER="ai_universe",
        AI_UNIVERSE_BASE_URL="http://localhost:9000",
        LLM_API_KEY=None,
    )
    gateway = ModelGateway(settings=custom_settings)

    result = await gateway.complete(
        messages=[{"role": "user", "content": "Decompose research plan."}],
        role="planner",
    )

    assert result is not None
    assert result.provider == "mock"
    assert len(result.text) > 0


def test_confidence_formula_with_ai_universe_multiplier():
    """Verify AI-Universe stated confidence acts as a multiplier in confidence formula v1."""
    # Baseline without AI-Universe
    score_base, _, details_base = compute_confidence_score(
        strongest_tier="STANDARD",
        independent_corroborations=2,
    )

    # With high AI-Universe confidence (1.0)
    score_high, _, details_high = compute_confidence_score(
        strongest_tier="STANDARD",
        independent_corroborations=2,
        ai_universe_confidence=1.0,
    )
    assert details_high["ai_universe_confidence"] == 1.0
    assert score_high == score_base

    # With reduced AI-Universe confidence from multi-agent debate (0.60)
    score_debated, _, details_debated = compute_confidence_score(
        strongest_tier="STANDARD",
        independent_corroborations=2,
        ai_universe_confidence=0.60,
    )
    assert details_debated["ai_universe_confidence"] == 0.60
    assert score_debated < score_base
    assert score_debated == pytest.approx(score_base * 0.60, abs=0.05)
