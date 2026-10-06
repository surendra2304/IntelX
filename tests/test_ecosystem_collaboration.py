"""Tests for StrateX and Futuris Ecosystem Integration and UI Visual Integrity."""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.connectors.search import SearchResult, WebSearchConnector, clean_rss_text
from intelx.core.auth import hash_api_key
from intelx.core.enums import ApiKeyRole, RunOutcome, RunStatus
from intelx.core.errors import ProviderError
from intelx.core.report import _clean_prose
from intelx.db.models import ApiKey, Finding, ResearchRun
from intelx.db.session import get_sessionmaker


async def _seed_member_key(name: str) -> str:
    raw_key = f"test-{name}-api-key"
    async with get_sessionmaker()() as session:
        session.add(
            ApiKey(
                key_hash=hash_api_key(raw_key),
                name=name,
                role=ApiKeyRole.MEMBER,
            )
        )
        await session.commit()
    return raw_key


@pytest.mark.asyncio
async def test_stratex_intelligence_research_endpoint_direct(monkeypatch):
    """Verify the StrateX contract when grounded market headlines are available."""

    async def fake_news_fetch(self, target, **kwargs):
        return [
            SearchResult(
                url="https://market.example.test/bitcoin-flows",
                title="Bitcoin rally follows institutional accumulation",
                snippet="Bitcoin gains as spot inflows rise.",
            ),
            SearchResult(
                url="https://market.example.test/etf-approval",
                title="SEC approves a spot Bitcoin ETF after court review",
                snippet="The approval changes the regulatory outlook.",
            ),
            SearchResult(
                url="https://market.example.test/fomc-outlook",
                title="FOMC interest rate and CPI inflation outlook",
                snippet="Treasury yields and liquidity remain in focus.",
            ),
        ]

    monkeypatch.setattr(WebSearchConnector, "fetch", fake_news_fetch)
    raw_key = await _seed_member_key("stratex-test")
    app = create_app()
    transport = ASGITransport(app=app)
    headers = {"X-API-Key": raw_key}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Direct StrateX client path (/v1/intelligence/research)
        payload = {
            "symbol": "BTCUSDT",
            "query": "What events are driving BTCUSDT volatility? Regulatory changes? Institutional flows? Macro events?",
            "trigger_reason": "VOLATILITY_2_SIGMA",
        }
        res = await client.post("/v1/intelligence/research", json=payload, headers=headers)
        assert res.status_code == 200, f"Error: {res.text}"
        data = res.json()

        # Check required fields expected by StrateX IntelXMarketClient
        assert data["symbol"] == "BTCUSDT"
        assert data["trigger_reason"] == "VOLATILITY_2_SIGMA"
        assert len(data["summary"]) > 10
        assert isinstance(data["findings"], dict)
        assert data["findings"]["status"] == "EVIDENCE_AVAILABLE"
        assert data["findings"]["sources_count"] == 3
        assert len(data["findings"]["evidence_sources"]) == 3
        assert all(
            source["url"].startswith("https://") for source in data["findings"]["evidence_sources"]
        )
        assert len(data["sentiment_drivers"]) > 0
        assert len(data["regulatory_changes"]) > 0
        assert len(data["macro_events"]) > 0
        assert isinstance(data["sentiment_score"], float)
        assert data["volatility_impact_factor"] >= 1.0
        assert data["expires_at"] > data["timestamp"]

        # 2. API v1 gateway path (/api/v1/intelligence/research)
        res_v1 = await client.post("/api/v1/intelligence/research", json=payload, headers=headers)
        assert res_v1.status_code == 200
        assert res_v1.json()["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_stratex_returns_no_synthetic_signals_without_evidence(monkeypatch):
    """A successful empty search must produce neutral insufficiency, not invented drivers."""

    async def empty_news_fetch(self, target, **kwargs):
        return []

    monkeypatch.setattr(WebSearchConnector, "fetch", empty_news_fetch)
    raw_key = await _seed_member_key("stratex-empty-search")
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/intelligence/research",
            json={"symbol": "NOEVIDENCE", "trigger_reason": "VOLATILITY_2_SIGMA"},
            headers={"X-API-Key": raw_key},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["findings"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert data["findings"]["sources_count"] == 0
    assert data["findings"]["evidence_sources"] == []
    assert data["sentiment_drivers"] == []
    assert data["regulatory_changes"] == []
    assert data["macro_events"] == []
    assert data["sentiment_score"] == 0.0
    assert data["volatility_impact_factor"] == 1.0
    assert "No verified market evidence" in data["summary"]


@pytest.mark.asyncio
async def test_stratex_returns_service_unavailable_when_live_search_fails(monkeypatch):
    """Provider outages without local evidence must not be disguised as market findings."""

    async def failed_news_fetch(self, target, **kwargs):
        raise ProviderError(
            "Live search returned no sources while providers failed.",
            details={"failed_providers": [{"provider": "google_news"}]},
        )

    monkeypatch.setattr(WebSearchConnector, "fetch", failed_news_fetch)
    raw_key = await _seed_member_key("stratex-search-outage")
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/intelligence/research",
            json={"symbol": "NOEVIDENCE", "trigger_reason": "VOLATILITY_2_SIGMA"},
            headers={"X-API-Key": raw_key},
        )

    assert response.status_code == 503
    assert "providers are unavailable" in response.json()["detail"]


@pytest.mark.asyncio
async def test_futuris_research_query_endpoints():
    """Return only evidence-backed reports that match the requested sector."""
    raw_key = await _seed_member_key("futuris-query-test")
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        answered_run = ResearchRun(
            objective="ETH institutional flows and volatility research",
            status=RunStatus.COMPLETED,
            outcome=RunOutcome.ANSWERED,
            completed_at=datetime.now(UTC),
        )
        failed_btc_run = ResearchRun(
            objective="BTC market research that failed before verification",
            status=RunStatus.FAILED,
            outcome=RunOutcome.FAILED,
            completed_at=datetime.now(UTC),
        )
        session.add_all([answered_run, failed_btc_run])
        await session.flush()
        session.add_all(
            [
                Finding(
                    run_id=answered_run.id,
                    conclusion="ETH rallied as institutional inflows increased; volatility remained elevated.",
                    confidence=0.91,
                ),
                Finding(
                    run_id=failed_btc_run.id,
                    conclusion="Unverified BTC baseline must not be exported.",
                    confidence=0.2,
                ),
            ]
        )
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"X-API-Key": raw_key}
        res = await client.get("/api/v1/research/query?sector=BTC", headers=headers)
        assert res.status_code == 200, f"Error: {res.text}"
        reports = res.json()
        assert isinstance(reports, list)
        # Do not widen to an unrelated sector or include a failed BTC run.
        assert reports == []

        # Also test /api/v1/futuris/query returns only the completed, answered ETH run.
        res_fut = await client.get("/api/v1/futuris/query?sector=ETH", headers=headers)
        assert res_fut.status_code == 200
        eth_reports = res_fut.json()
        assert len(eth_reports) == 1
        report = eth_reports[0]
        assert report["report_id"] == answered_run.id
        assert report["asset_or_sector"] == "ETH"
        assert report["summary"] == (
            "ETH rallied as institutional inflows increased; volatility remained elevated."
        )
        assert report["key_findings"] == [report["summary"]]
        assert report["sentiment_score"] > 0
        assert report["volatility_impact_factor"] == 1.35


@pytest.mark.asyncio
async def test_ecosystem_signal_trigger_endpoints():
    """Verify manual / webhook signal trigger endpoints for StrateX and Futuris."""
    raw_key = await _seed_member_key("ecosystem-signal-test")
    app = create_app()
    transport = ASGITransport(app=app)
    headers = {"X-API-Key": raw_key}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Trigger StrateX signal
        st_res = await client.post(
            "/api/v1/stratex/trigger-signal",
            headers=headers,
            json={
                "finding_text": "Bullish ETF inflow acceleration indicates institutional spot accumulation",
                "run_id": "test-run-123",
                "domain": "market",
                "confidence": 0.92,
            },
        )
        assert st_res.status_code == 200
        assert st_res.json()["category"] == "actionable_trade_signal"

        # Trigger Futuris forecast
        fu_res = await client.post(
            "/api/v1/futuris/trigger-forecast",
            headers=headers,
            json={
                "finding_text": "Supply shock breakthrough creates rapid adoption acceleration",
                "run_id": "test-run-123",
                "domain": "market",
                "confidence": 0.88,
            },
        )
        assert fu_res.status_code == 200
        assert fu_res.json()["category"] == "market_moving"


def test_rss_and_prose_cleaning():
    """Verify HTML entities and raw Google News anchor tags are completely scrubbed."""
    dirty_rss = (
        '&lt;a href="https://news.google.com/rss/articles/CBMi'
        'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"&gt;'
        "Realme GT 7 Pro Launch Announcement&lt;/a&gt;&amp;nbsp;&amp;nbsp;"
        '&lt;font color="#6f6f6f"&gt;GSMArena&lt;/font&gt;'
    )
    cleaned = clean_rss_text(dirty_rss)
    assert "<" not in cleaned
    assert ">" not in cleaned
    assert "https://news.google.com" not in cleaned
    assert "Realme GT 7 Pro Launch Announcement" in cleaned
    assert "&nbsp;" not in cleaned

    dirty_prose = (
        'Analysis on &lt;font color="red"&gt;regulatory action&lt;/font&gt;&nbsp;in market.'
    )
    cleaned_prose = _clean_prose(dirty_prose)
    assert "<font" not in cleaned_prose
    assert "regulatory action" in cleaned_prose
    assert "\xa0" not in cleaned_prose
