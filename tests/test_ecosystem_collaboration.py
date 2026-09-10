"""Tests for StrateX and Futuris Ecosystem Integration and UI Visual Integrity."""

import pytest
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.connectors.search import clean_rss_text
from intelx.core.report import _clean_prose
from intelx.core.settings import get_settings


@pytest.mark.asyncio
async def test_stratex_intelligence_research_endpoint_direct():
    """Verify StrateX client endpoint POST /v1/intelligence/research satisfies StrateX contract."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Direct StrateX client path (/v1/intelligence/research)
        payload = {
            "symbol": "BTCUSDT",
            "query": "What events are driving BTCUSDT volatility? Regulatory changes? Institutional flows? Macro events?",
            "trigger_reason": "VOLATILITY_2_SIGMA",
        }
        res = await client.post("/v1/intelligence/research", json=payload)
        assert res.status_code == 200, f"Error: {res.text}"
        data = res.json()

        # Check required fields expected by StrateX IntelXMarketClient
        assert data["symbol"] == "BTCUSDT"
        assert data["trigger_reason"] == "VOLATILITY_2_SIGMA"
        assert len(data["summary"]) > 10
        assert isinstance(data["findings"], dict)
        assert len(data["sentiment_drivers"]) > 0
        assert len(data["regulatory_changes"]) > 0
        assert len(data["macro_events"]) > 0
        assert isinstance(data["sentiment_score"], float)
        assert data["volatility_impact_factor"] >= 1.0
        assert data["expires_at"] > data["timestamp"]

        # 2. API v1 gateway path (/api/v1/intelligence/research)
        res_v1 = await client.post("/api/v1/intelligence/research", json=payload)
        assert res_v1.status_code == 200
        assert res_v1.json()["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_futuris_research_query_endpoints():
    """Verify Futuris research query endpoint /api/v1/research/query returns expected schema."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"X-API-Key": "intelx_api"}
        res = await client.get("/api/v1/research/query?sector=BTC", headers=headers)
        assert res.status_code == 200, f"Error: {res.text}"
        reports = res.json()
        assert isinstance(reports, list)
        assert len(reports) > 0
        r0 = reports[0]
        assert "report_id" in r0
        assert "asset_or_sector" in r0
        assert "published_at" in r0
        assert "summary" in r0
        assert "sentiment_score" in r0
        assert "volatility_impact_factor" in r0
        assert "key_findings" in r0
        assert isinstance(r0["key_findings"], list)

        # Also test /api/v1/futuris/query
        res_fut = await client.get("/api/v1/futuris/query?sector=ETH", headers=headers)
        assert res_fut.status_code == 200
        assert len(res_fut.json()) > 0


@pytest.mark.asyncio
async def test_ecosystem_signal_trigger_endpoints():
    """Verify manual / webhook signal trigger endpoints for StrateX and Futuris."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Trigger StrateX signal
        st_res = await client.post(
            "/api/v1/stratex/trigger-signal",
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
            headers={"X-API-Key": "intelx_api"},
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
        'Realme GT 7 Pro Launch Announcement&lt;/a&gt;&amp;nbsp;&amp;nbsp;'
        '&lt;font color="#6f6f6f"&gt;GSMArena&lt;/font&gt;'
    )
    cleaned = clean_rss_text(dirty_rss)
    assert "<" not in cleaned
    assert ">" not in cleaned
    assert "https://news.google.com" not in cleaned
    assert "Realme GT 7 Pro Launch Announcement" in cleaned
    assert "&nbsp;" not in cleaned

    dirty_prose = 'Analysis on &lt;font color="red"&gt;regulatory action&lt;/font&gt;&nbsp;in market.'
    cleaned_prose = _clean_prose(dirty_prose)
    assert "<font" not in cleaned_prose
    assert "regulatory action" in cleaned_prose
    assert "\xa0" not in cleaned_prose
