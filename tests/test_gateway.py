"""Tests for INTELX ModelGateway, MockProvider, and Structured Output self-correction."""

import pytest
from pydantic import BaseModel, Field

from intelx.core.errors import StructuredOutputError
from intelx.core.settings import Settings
from intelx.models.gateway import ModelGateway
from intelx.models.providers import MockProvider
from intelx.models.types import ModelResult


class PlanSchema(BaseModel):
    objective: str
    subquestions: list[str]
    stages: list[str]


class VerdictSchema(BaseModel):
    verdict: str
    confidence: float
    reasoning: str
    contradictions: list[str] = Field(default_factory=list)


class CustomSchema(BaseModel):
    topic: str
    score: float
    tags: list[str]


@pytest.mark.asyncio
async def test_mock_provider_roles_and_schemas():
    """Verify MockProvider generates valid structured data for all standard roles."""
    provider = MockProvider()

    # 1. Planner
    text, usage = await provider.complete(
        messages=[{"role": "user", "content": "Plan an investigation on solid-state batteries."}],
        model="mock-gpt-4o",
        role="planner",
        schema_model=PlanSchema,
    )
    plan = PlanSchema.model_validate_json(text)
    assert len(plan.subquestions) >= 2
    assert "stages" in text
    assert usage.input_tokens > 0
    assert usage.output_tokens > 0
    assert usage.usd_cost > 0.0

    # 2. Verifier
    text_v, usage_v = await provider.complete(
        messages=[{"role": "user", "content": "Verify claim"}],
        model="mock-gpt-4o",
        role="verifier",
        schema_model=VerdictSchema,
    )
    verdict = VerdictSchema.model_validate_json(text_v)
    assert verdict.verdict == "VERIFIED"
    assert verdict.confidence > 0.8

    # 3. Arbitrary Custom Schema
    text_c, usage_c = await provider.complete(
        messages=[{"role": "user", "content": "Score this"}],
        model="mock-gpt-4o",
        role="analyst",
        schema_model=CustomSchema,
    )
    custom = CustomSchema.model_validate_json(text_c)
    assert isinstance(custom.topic, str)
    assert isinstance(custom.score, float)


@pytest.mark.asyncio
async def test_gateway_role_routing_and_pricing():
    """Verify gateway routes to role-specific model and attaches usage costs."""
    settings = Settings(
        MOCK_MODE=True,
        LLM_MODEL="default-llm",
        LLM_MODEL_PLANNER="custom-planner-model",
        LLM_MODEL_VERIFIER="custom-verifier-model",
    )
    gateway = ModelGateway(settings=settings)

    # Planner call should resolve custom planner model
    res_planner = await gateway.complete(
        messages=[{"role": "user", "content": "Create research plan"}],
        role="planner",
        schema_model=PlanSchema,
    )
    assert isinstance(res_planner, ModelResult)
    assert res_planner.model == "custom-planner-model"
    assert res_planner.provider == "mock"
    assert isinstance(res_planner.parsed, PlanSchema)
    assert res_planner.usage.usd_cost > 0.0

    # Synthesizer call should fall back to default LLM
    res_synth = await gateway.complete(
        messages=[{"role": "user", "content": "Synthesize report"}],
        role="synthesizer",
    )
    assert res_synth.model == "default-llm"
    assert "Mock research synthesis" in res_synth.text


@pytest.mark.asyncio
async def test_gateway_markdown_fence_stripping():
    """Verify gateway cleanly extracts JSON wrapped in markdown fences."""
    gateway = ModelGateway()
    raw_markdown = (
        '```json\n{\n  "topic": "Fusion Energy",\n  "score": 0.94,\n  '
        '"tags": ["clean-energy", "tokamak"]\n}\n```'
    )

    parsed, err = gateway._try_parse_schema(raw_markdown, CustomSchema)
    assert err is None
    assert parsed is not None
    assert parsed.topic == "Fusion Energy"
    assert parsed.score == 0.94
    assert "tokamak" in parsed.tags


@pytest.mark.asyncio
async def test_gateway_structured_output_retry_and_failure():
    """Verify gateway retries on schema invalidity and raises StructuredOutputError if failing."""
    settings = Settings(MOCK_MODE=True)
    gateway = ModelGateway(settings=settings)

    # Monkeypatch gateway provider to return bad text
    class DefectiveProvider:
        async def complete(self, messages, **kwargs):
            from intelx.models.types import Usage

            return '{"invalid_field": 123}', Usage(
                input_tokens=10, output_tokens=10, usd_cost=0.00002
            )

    gateway._mock_provider = DefectiveProvider()

    with pytest.raises(StructuredOutputError) as exc_info:
        await gateway.complete(
            messages=[{"role": "user", "content": "Extract custom info"}],
            role="analyst",
            schema_model=CustomSchema,
        )

    assert "Model output failed schema validation" in str(exc_info.value)
    assert exc_info.value.details.get("role") == "analyst"
