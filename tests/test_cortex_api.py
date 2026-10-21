"""Tests for Cortex Website Operations & Lead Intelligence API Router and Connector."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from intelx.app.factory import create_app
from intelx.core.auth import hash_api_key
from intelx.core.enums import ApiKeyRole, RunOutcome, RunStatus
from intelx.db.base import Base
from intelx.db.engine import get_async_engine
from intelx.db.models import ApiKey, Finding, ResearchRun
from intelx.db.session import get_sessionmaker
from intelx.integrations.cortex_context import (
    CortexConnector,
)


def test_cortex_extract_domain():
    """Verify domain extraction from various input formats."""
    assert CortexConnector.extract_domain("acme.com") == "acme.com"
    assert CortexConnector.extract_domain("https://www.stripe.com/pricing") == "www.stripe.com"
    assert CortexConnector.extract_domain("alex@openai.com") == "openai.com"
    assert CortexConnector.extract_domain("http://sub.domain.org:8080/path") == "sub.domain.org"


def test_cortex_detect_lead_relevance():
    """Verify lead keywords trigger actionable classification."""
    is_sig, cat, targets = CortexConnector.detect_lead_relevance(
        "Prospect expressed interest in enterprise B2B SaaS pricing"
    )
    assert is_sig is True
    assert cat == "actionable_lead_intel"
    assert "WEBSITE_PROSPECT" in targets

    is_sig_gen, cat_gen, _ = CortexConnector.detect_lead_relevance("General research text")
    assert is_sig_gen is True
    assert cat_gen == "general_web_intel"


def test_cortex_synthesize_lead_dossier():
    """Verify dossier synthesis from findings or claims."""
    findings = [
        {"conclusion": "Acme Corp announced Series B funding.", "confidence": 0.9},
        {"conclusion": "Acme is scaling cloud infrastructure.", "confidence": 0.85},
    ]
    dossier = CortexConnector.synthesize_lead_dossier("acme.com", findings=findings)
    assert dossier.target_domain == "acme.com"
    assert dossier.company_name == "Acme"
    assert len(dossier.key_findings) == 2
    assert len(dossier.talking_points_for_cortex) == 2
    assert "Series B" in dossier.key_findings[0]


@pytest_asyncio.fixture
async def cortex_client() -> AsyncGenerator[AsyncClient, None]:
    """Test client for Cortex routes with seeded delegation key."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        test_key = "cortex-test-delegation-key"
        key_hash = hash_api_key(test_key)
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        if not (await session.execute(stmt)).scalar_one_or_none():
            session.add(
                ApiKey(
                    key_hash=key_hash,
                    name="cortex-delegation",
                    role=ApiKeyRole.MEMBER,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

        # Seed sample completed run for 'stripe.com'
        run_stripe = ResearchRun(
            objective="OSINT analysis of stripe.com developer platform",
            status=RunStatus.COMPLETED,
            outcome=RunOutcome.ANSWERED,
            created_at=datetime.now(UTC),
        )
        session.add(run_stripe)
        await session.flush()

        finding_stripe = Finding(
            run_id=run_stripe.id,
            conclusion="Stripe expanded global payment processing into 12 new regions.",
            confidence=0.92,
            created_at=datetime.now(UTC),
        )
        session.add(finding_stripe)
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": "cortex-test-delegation-key"},
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_cortex_enrich_lead_endpoint_with_seeded_data(cortex_client: AsyncClient):
    """Test /v1/cortex/enrich-lead finds existing research for domain."""
    resp = await cortex_client.post(
        "/v1/cortex/enrich-lead",
        json={"domain": "https://stripe.com", "company_name": "Stripe, Inc."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_domain"] == "stripe.com"
    assert data["company_name"] == "Stripe, Inc."
    assert any("payment processing" in f for f in data["key_findings"])


@pytest.mark.asyncio
async def test_cortex_enrich_lead_endpoint_unknown_domain(cortex_client: AsyncClient):
    """Test /v1/cortex/enrich-lead synthesizes baseline dossier for fresh domain."""
    resp = await cortex_client.post(
        "/v1/cortex/enrich-lead",
        json={"domain": "unknown-lead-corp.io"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_domain"] == "unknown-lead-corp.io"
    assert "Unknown-Lead-Corp" in data["company_name"]
    assert len(data["talking_points_for_cortex"]) >= 1


@pytest.mark.asyncio
async def test_cortex_enrich_lead_endpoint_invalid_domain(cortex_client: AsyncClient):
    """Test /v1/cortex/enrich-lead rejects empty domain."""
    resp = await cortex_client.post(
        "/v1/cortex/enrich-lead",
        json={"domain": ""},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cortex_visitor_query_with_local_finding(cortex_client: AsyncClient):
    """Test /v1/cortex/visitor-query answers matching local indexed finding."""
    resp = await cortex_client.post(
        "/v1/cortex/visitor-query",
        json={"query": "payment processing regions"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "payment processing" in data["answer"]
    assert len(data["sources"]) >= 1
    assert data["confidence"] > 0.8


@pytest.mark.asyncio
async def test_cortex_visitor_query_empty_error(cortex_client: AsyncClient):
    """Test /v1/cortex/visitor-query validates non-empty query."""
    resp = await cortex_client.post(
        "/v1/cortex/visitor-query",
        json={"query": "   "},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cortex_trigger_lead_intel_dispatch(cortex_client: AsyncClient):
    """Test /v1/cortex/trigger-lead-intel dispatches notification."""
    resp = await cortex_client.post(
        "/v1/cortex/trigger-lead-intel",
        json={
            "finding_text": "Prospect company evaluated B2B SaaS integration for Q4",
            "run_id": "run-test-trigger",
            "domain": "general",
            "confidence": 0.88,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("delivered", "delivered_mock")
    assert data["event"] == "website_lead_intel"


@pytest.mark.asyncio
async def test_cortex_connector_mock_delivery():
    """Test CortexConnector handles mock mode gracefully."""
    with patch("intelx.integrations.cortex_context.get_settings") as mock_settings:
        mock_settings.return_value.MOCK_MODE = True
        mock_settings.return_value.CORTEX_WEBHOOK_URL = None
        mock_settings.return_value.CORTEX_BASE_URL = "http://cortex:8000"

        res = await CortexConnector.notify_cortex_lead_intel(
            finding_text="Lead signed up for enterprise trial",
            run_id="run-mock-1",
        )
        assert res["status"] == "delivered_mock"
        assert res["event"] == "website_lead_intel"


@pytest.mark.asyncio
async def test_cortex_connector_live_http_delivery():
    """Test CortexConnector dispatches HTTP POST over custom client."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-API-Key") == "test-cortex-key"
        return httpx.Response(200, json={"status": "accepted", "lead_id": "lead-123"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        with patch("intelx.integrations.cortex_context.get_settings") as mock_settings:
            mock_settings.return_value.MOCK_MODE = False
            mock_settings.return_value.CORTEX_WEBHOOK_URL = "http://cortex:8000/api/v1/webhooks/intelx-lead-intel"
            mock_settings.return_value.CORTEX_API_KEY = "test-cortex-key"

            res = await CortexConnector.notify_cortex_lead_intel(
                finding_text="Lead submitted high-intent demo request",
                run_id="run-http-1",
                client=http_client,
            )
            assert res["status"] == "delivered"
            assert res["status_code"] == 200
