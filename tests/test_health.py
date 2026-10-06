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
