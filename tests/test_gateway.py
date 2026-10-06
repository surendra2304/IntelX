"""Tests for INTELX ModelGateway, MockProvider, and Structured Output self-correction."""

import pytest
from pydantic import BaseModel, Field

from intelx.core.errors import ProviderError, StructuredOutputError
from intelx.core.settings import Settings
from intelx.models.gateway import ModelGateway
from intelx.models.providers import MockProvider
from intelx.models.types import ModelResult, Usage


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


def test_mock_extractor_keeps_first_body_sentence_after_unpunctuated_metadata() -> None:
    """Headers without terminal punctuation must not hide the first evidence sentence."""
    document = (
        "# Silicon Anode Report\n"
        "Published: 2026-05-01\n"
        "Domain: nature.com\n"
        "Publisher: Springer Nature\n\n"
        "Silicon composite anodes reached a gravimetric cell energy density of 420 Wh/kg.\n"
        "The porous carbon matrix accommodated up to 280% expansion."
    )

    result = MockProvider._mock_extract_claims([{"role": "user", "content": document}])
    target = next(claim for claim in result["claims"] if "420 Wh/kg" in claim["quote"])

    assert target["claim_type"] == "MEASUREMENT"
    assert target["quote"] == (
        "Silicon composite anodes reached a gravimetric cell energy density of 420 Wh/kg."
    )
    assert (
        document[target["relative_span"]["start"] : target["relative_span"]["end"]]
        == target["quote"]
    )


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


def test_gateway_propagates_injected_provider_settings():
    """Provider adapters must use the gateway's configured endpoint and credentials."""
    inference_settings = Settings(
        MOCK_MODE=False,
        LLM_PROVIDER="inference",
        INFERENCE_URL="https://inference.example.test",
        INFERENCE_API_KEY="local-inference-test-key",
    )
    inference_name, inference_provider = ModelGateway(inference_settings)._get_provider()
    assert inference_name == "inference"
    assert inference_provider.base_url == "https://inference.example.test"
    assert inference_provider.api_key == "local-inference-test-key"
    assert inference_provider.settings is inference_settings

    openai_settings = Settings(
        MOCK_MODE=False,
        LLM_PROVIDER="openai_compatible",
        LLM_BASE_URL="https://llm.example.test/v1",
        OPENAI_API_KEY="local-openai-test-key",
    )
    _, openai_provider = ModelGateway(openai_settings)._get_provider()
    assert openai_provider.base_url == "https://llm.example.test/v1"
    assert openai_provider.api_key == "local-openai-test-key"
    assert openai_provider.settings is openai_settings

    anthropic_settings = Settings(
        MOCK_MODE=False,
        LLM_PROVIDER="anthropic",
        ANTHROPIC_API_KEY="local-anthropic-test-key",
    )
    _, anthropic_provider = ModelGateway(anthropic_settings)._get_provider()
    assert anthropic_provider.api_key == "local-anthropic-test-key"
    assert anthropic_provider.settings is anthropic_settings


def test_provider_specific_credentials_do_not_cross_contaminate():
    """When both keys are configured, each backend must receive its own credential."""
    settings = Settings(
        LLM_PROVIDER="anthropic",
        LLM_API_KEY="local-generic-test-key",
        OPENAI_API_KEY="local-openai-test-key",
        ANTHROPIC_API_KEY="local-anthropic-test-key",
    )
    assert settings.get_llm_api_key("anthropic") == "local-anthropic-test-key"
    assert settings.get_llm_api_key("openai_compatible") == "local-openai-test-key"

    generic_only = Settings(LLM_PROVIDER="anthropic", LLM_API_KEY="local-generic-test-key")
    assert generic_only.get_llm_api_key("anthropic") == "local-generic-test-key"


@pytest.mark.asyncio
async def test_gateway_provider_failure_does_not_silently_return_mock_answer(monkeypatch):
    """Live-provider outages must fail visibly unless mock fallback was explicitly enabled."""
    settings = Settings(
        ENV="development",
        MOCK_MODE=False,
        LLM_PROVIDER="inference",
        ALLOW_MOCK_FALLBACK=False,
    )
    gateway = ModelGateway(settings=settings)

    class FailingProvider:
        async def complete(self, **_kwargs):
            raise ProviderError("simulated provider outage")

    monkeypatch.setattr(gateway, "_get_provider", lambda: ("inference", FailingProvider()))

    with pytest.raises(ProviderError, match="mock fallback is disabled"):
        await gateway.complete(
            messages=[{"role": "user", "content": "Research a current real-world question."}],
            role="analyst",
        )


@pytest.mark.asyncio
async def test_invalid_live_provider_schema_does_not_silently_fall_back_to_mock(monkeypatch):
    """Malformed live output must not become a synthetic answer without explicit opt-in."""
    settings = Settings(
        ENV="development",
        MOCK_MODE=False,
        LLM_PROVIDER="inference",
        ALLOW_MOCK_FALLBACK=False,
    )
    gateway = ModelGateway(settings=settings)

    class MalformedProvider:
        calls = 0

        async def complete(self, **_kwargs):
            self.calls += 1
            return "not valid JSON", Usage(input_tokens=1, output_tokens=1, usd_cost=0.0)

    class ForbiddenMockFallback:
        async def complete(self, **_kwargs):
            pytest.fail("MockProvider was called without explicit fallback opt-in")

    provider = MalformedProvider()
    gateway._mock_provider = ForbiddenMockFallback()
    monkeypatch.setattr(gateway, "_get_provider", lambda: ("inference", provider))

    with pytest.raises(StructuredOutputError, match="synthetic fallback is disabled"):
        await gateway.complete(
            messages=[{"role": "user", "content": "Return a structured research plan."}],
            role="planner",
            schema_model=PlanSchema,
        )
    assert provider.calls == 2


def test_production_rejects_mock_fallback_configuration():
    """Production settings must reject the development-only synthetic fallback switch."""
    settings = Settings(
        ENV="production",
        MOCK_MODE=False,
        LLM_PROVIDER="inference",
        LLM_MODEL="production-research-model",
        ALLOW_MOCK_FALLBACK=True,
    )
    with pytest.raises(RuntimeError, match="Synthetic mock fallback is never allowed"):
        settings.validate_production_security()


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
