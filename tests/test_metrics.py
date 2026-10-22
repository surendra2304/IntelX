"""Tests for Prometheus Telemetry Metrics and Health Endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.core.metrics import (
    ACTIVE_RUNS,
    CLAIMS_EXTRACTED_TOTAL,
    FINDINGS_PRODUCED_TOTAL,
    RUNS_TOTAL,
    SOURCES_RETRIEVED_TOTAL,
)


@pytest.mark.asyncio
async def test_healthz_and_readyz_endpoints():
    """Verify GET /healthz and GET /readyz probes return expected structure."""
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Healthz (liveness)
        resp_h = await client.get("/healthz")
        assert resp_h.status_code == 200
        data_h = resp_h.json()
        assert data_h["status"] == "ok"
        assert "service" in data_h

        # Readyz (readiness)
        resp_r = await client.get("/readyz")
        assert resp_r.status_code == 200
        data_r = resp_r.json()
        assert data_r["status"] == "ready"
        assert data_r["ready"] is True
        assert data_r["database"] == "ok"
        assert data_r["storage"] == "ok"


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint():
    """Verify GET /metrics returns valid Prometheus exposition text with required metrics."""
    # Increment metrics
    RUNS_TOTAL.labels(status="COMPLETED").inc()
    SOURCES_RETRIEVED_TOTAL.inc(3)
    CLAIMS_EXTRACTED_TOTAL.inc(5)
    FINDINGS_PRODUCED_TOTAL.labels(status="verified").inc(2)
    ACTIVE_RUNS.set(1)

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        body = resp.text

        assert "intelx_runs_total" in body
        assert "intelx_sources_retrieved_total" in body
        assert "intelx_claims_extracted_total" in body
        assert "intelx_findings_produced_total" in body
        assert "intelx_active_runs" in body
