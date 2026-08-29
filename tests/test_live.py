"""Live Provider Bring-Up and Fast-Fail Diagnostic Tests (gated by @pytest.mark.live)."""

import os

import pytest
from pydantic import BaseModel, Field

from intelx.core.errors import ProviderError
from intelx.core.settings import Settings
from intelx.models.gateway import ModelGateway
from intelx.models.providers import OpenAICompatibleProvider


class DiagnosticSchema(BaseModel):
    status: str = Field(description="Operational status")
    role: str = Field(description="Agent role tested")


@pytest.mark.live
@pytest.mark.asyncio
async def test_openai_compatible_live_completion():
    """Verify live OpenAI-compatible provider roundtrip with structured schema."""
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("INTELX_LLM_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY or INTELX_LLM_API_KEY not configured")

    settings = Settings(
        MOCK_MODE=False,
        LLM_PROVIDER="openai_compatible",
        LLM_API_KEY=api_key,
        LLM_MODEL=os.getenv("INTELX_LLM_MODEL", "gpt-4o-mini"),
    )
    gateway = ModelGateway(settings=settings)
    res = await gateway.complete(
        messages=[
            {"role": "system", "content": "You are a test agent. Output valid JSON."},
            {"role": "user", "content": "Diagnostic self-test. Return status OK for role planner."},
        ],
        role="planner",
        schema_model=DiagnosticSchema,
    )
    assert res.parsed is not None
    assert res.parsed.status.upper() == "OK"
    assert res.usage.input_tokens > 0
    assert res.usage.output_tokens > 0
    assert res.usage.usd_cost > 0.0


@pytest.mark.live
@pytest.mark.asyncio
async def test_anthropic_live_completion():
    """Verify live Anthropic Claude provider roundtrip with tool-forced schema."""
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("INTELX_LLM_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY or INTELX_LLM_API_KEY not configured")

    settings = Settings(
        MOCK_MODE=False,
        LLM_PROVIDER="anthropic",
        LLM_API_KEY=api_key,
        LLM_MODEL=os.getenv("INTELX_LLM_MODEL", "claude-3-5-haiku-20241022"),
    )
    gateway = ModelGateway(settings=settings)
    res = await gateway.complete(
        messages=[
            {"role": "system", "content": "You are a test agent. Output valid JSON."},
            {"role": "user", "content": "Diagnostic self-test. Return status OK for role planner."},
        ],
        role="planner",
        schema_model=DiagnosticSchema,
    )
    assert res.parsed is not None
    assert res.parsed.status.upper() == "OK"
    assert res.usage.input_tokens > 0
    assert res.usage.output_tokens > 0
    assert res.usage.usd_cost > 0.0


@pytest.mark.asyncio
async def test_live_provider_fail_fast_invalid_key():
    """Verify live provider with invalid API key fails fast without hanging or retrying endlessly."""
    provider = OpenAICompatibleProvider(api_key="invalid-key-sk-dummy-12345")
    with pytest.raises(ProviderError) as excinfo:
        await provider.complete(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o-mini",
            role="planner",
        )
    assert (
        "failed after attempt" in str(excinfo.value)
        or "invalid" in str(excinfo.value).lower()
        or "401" in str(excinfo.value)
    )
