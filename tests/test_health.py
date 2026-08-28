"""Tests for system health, readiness, version, and middleware endpoints."""

import pytest
from httpx import AsyncClient

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
