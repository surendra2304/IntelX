"""Tests for system health, readiness, version, and middleware endpoints."""

import json

import pytest
from fastapi.responses import JSONResponse
from httpx import AsyncClient

import intelx.api.v1.health as health_module
from intelx.core.settings import Settings
from intelx.core.version import PROJECT_NAME, __version__


@pytest.mark.asyncio
async def test_healthz_endpoint(client: AsyncClient):
    """Test /healthz reports operational status, version, mock_mode, and database ok."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == PROJECT_NAME
    assert data["version"] == __version__
    assert data["mock_mode"] is True
    assert data["database"] == "ok"
    assert data["evidence_class"] == "process_liveness"
    assert "observed_at" in data
    assert "timestamp" in data

    # Verify Request ID headers
    assert "x-request-id" in response.headers
    assert "x-response-time" in response.headers


@pytest.mark.asyncio
async def test_readyz_endpoint(client: AsyncClient):
    """Test /readyz reports ready status."""
    response = await client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["ready"] is True
    assert data["database"] == "ok"
    assert data["evidence_class"] == "dependency_readiness"
    assert "observed_at" in data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "provider_keys", "expected_ready"),
    [
        ("inference", {"INFERENCE_API_KEY": None}, False),
        ("inference", {"INFERENCE_API_KEY": "local-inference-test-key"}, True),
        (
            "anthropic",
            {"OPENAI_API_KEY": "local-openai-test-key"},
            False,
        ),
        (
            "anthropic",
            {"ANTHROPIC_API_KEY": "local-anthropic-test-key"},
            True,
        ),
        (
            "openai_compatible",
            {"OPENAI_API_KEY": "local-openai-test-key"},
            True,
        ),
    ],
)
async def test_readyz_requires_selected_provider_credentials(
    monkeypatch, tmp_path, provider, provider_keys, expected_ready
):
    """Readiness checks the selected provider's config, not a different provider's key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("INTELX_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("INTELX_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("INTELX_LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    settings = Settings(
        MOCK_MODE=False,
        LLM_PROVIDER=provider,
        DATA_DIR=str(tmp_path),
        **provider_keys,
    )
    monkeypatch.setattr(health_module, "get_settings", lambda: settings)

    async def database_is_healthy():
        return True

    monkeypatch.setattr(health_module, "check_database_health", database_is_healthy)
    result = await health_module.readyz()
    if isinstance(result, JSONResponse):
        status_code = result.status_code
        payload = json.loads(result.body)
    else:
        status_code = 200
        payload = result

    assert payload["ready"] is expected_ready
    assert (status_code == 200) is expected_ready
    assert payload["model_provider_check"] == "configuration_only"


@pytest.mark.asyncio
async def test_version_endpoint(client: AsyncClient):
    """Test /api/v1/version returns valid platform metadata."""
    response = await client.get("/api/v1/version")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == PROJECT_NAME
    assert data["version"] == __version__
    assert data["env"] == "testing"
    assert data["mock_mode"] is True
    assert "llm_provider" in data


@pytest.mark.asyncio
async def test_request_id_propagation(client: AsyncClient):
    """Test custom X-Request-ID header is preserved and echoed back."""
    custom_id = "custom-test-request-id-12345"
    response = await client.get("/healthz", headers={"x-request-id": custom_id})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == custom_id


@pytest.mark.asyncio
async def test_metrics_endpoint(client: AsyncClient):
    """Test /metrics returns prometheus formatted text."""
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers.get("content-type") is not None


@pytest.mark.asyncio
async def test_health_head_and_alias_endpoints(client: AsyncClient):
    """Test HEAD and alias routes for healthz and readyz."""
    res_head = await client.head("/healthz")
    assert res_head.status_code == 200

    res_alias = await client.get("/health")
    assert res_alias.status_code == 200
    assert res_alias.json()["status"] == "ok"

    res_ready_head = await client.head("/readyz")
    assert res_ready_head.status_code == 200
