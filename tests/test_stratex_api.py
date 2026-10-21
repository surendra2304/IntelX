"""Tests for StrateX Algorithmic Trading Intelligence API Router (intelx/api/v1/stratex.py)."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from intelx.api.v1.stratex import _clean_symbol
from intelx.app.factory import create_app
from intelx.connectors.search import SearchResult
from intelx.core.auth import hash_api_key
from intelx.core.enums import ApiKeyRole, RunOutcome, RunStatus
from intelx.core.errors import ProviderError
from intelx.db.base import Base
from intelx.db.engine import get_async_engine
from intelx.db.models import ApiKey, Finding, ResearchRun
from intelx.db.session import get_sessionmaker


def test_clean_symbol_normalization():
    """Verify ticker normalization trims common trading pair suffixes."""
    assert _clean_symbol("BTCUSDT") == "BTC"
    assert _clean_symbol("ETHPERP") == "ETH"
    assert _clean_symbol("SOLUSD") == "SOL"
    assert _clean_symbol("ADABUSD") == "ADA"
    assert _clean_symbol("AVAXUSDC") == "AVAX"
    assert _clean_symbol("DOTEUR") == "DOT"
    assert _clean_symbol("BTC") == "BTC"
    assert _clean_symbol("eth") == "ETH"


@pytest_asyncio.fixture
async def stratex_client() -> AsyncGenerator[AsyncClient, None]:
    """Test client for StrateX routes with seeded API key and sample research runs."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        test_key = "stratex-test-key-555"
        key_hash = hash_api_key(test_key)
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        if not (await session.execute(stmt)).scalar_one_or_none():
            session.add(
                ApiKey(
                    key_hash=key_hash,
                    name="stratex-test-key",
                    role=ApiKeyRole.MEMBER,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

        # Seed sample completed run for BTC (including explicit 'BTC' in objective)
        run_btc = ResearchRun(
            objective="Analyze BTC spot ETF inflows and macro catalysts",
            status=RunStatus.COMPLETED,
            outcome=RunOutcome.ANSWERED,
            scope_json={"domain": "market"},
            created_at=datetime.now(UTC),
        )
        session.add(run_btc)
        await session.flush()

        finding_bullish = Finding(
            run_id=run_btc.id,
            conclusion="Bitcoin BTC surge driven by institutional ETF net inflows and treasury demand.",
            confidence=0.92,
            created_at=datetime.now(UTC),
        )
        session.add(finding_bullish)

        finding_regulatory = Finding(
            run_id=run_btc.id,
            conclusion="SEC compliance review approved multiple commodity-backed ETFs for BTC.",
            confidence=0.88,
            created_at=datetime.now(UTC),
        )
        session.add(finding_regulatory)
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": "stratex-test-key-555"},
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_stratex_market_research_with_db_and_mocked_search(stratex_client: AsyncClient):
    """Verify /api/v1/intelligence/research combines local findings and live search."""
    mock_results = [
        SearchResult(
            url="https://macro.test/fomc-liquidity",
            title="Fed signals interest rate liquidity adjustments at FOMC meeting",
            snippet="Federal Reserve treasury yields drop as interest rate cuts are anticipated.",
        ),
        SearchResult(
            url="https://crypto.test/bull-rally",
            title="Crypto markets rally as bullish institutional accumulation accelerates",
            snippet="Major assets gain over 8% in heavy trading volume.",
        ),
    ]

    with patch(
        "intelx.api.v1.stratex.WebSearchConnector.fetch",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        res = await stratex_client.post(
            "/api/v1/intelligence/research",
            json={
                "symbol": "BTCUSDT",
                "trigger_reason": "VOLATILITY_2_SIGMA",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["symbol"] == "BTCUSDT"
        assert data["trigger_reason"] == "VOLATILITY_2_SIGMA"
        assert data["volatility_impact_factor"] == 1.45  # VOLATILITY trigger multiplier
        assert data["sentiment_score"] > 0.0  # Bullish sentiment
        assert len(data["sentiment_drivers"]) >= 1
        assert len(data["regulatory_changes"]) >= 1
        assert len(data["macro_events"]) >= 1
        assert data["findings"]["status"] == "EVIDENCE_AVAILABLE"


@pytest.mark.asyncio
async def test_stratex_market_research_trigger_multipliers(stratex_client: AsyncClient):
    """Verify different trigger reasons modulate the volatility multiplier."""
    with patch(
        "intelx.api.v1.stratex.WebSearchConnector.fetch",
        new_callable=AsyncMock,
        return_value=[],
    ):
        # Drawdown trigger
        res_dd = await stratex_client.post(
            "/api/v1/intelligence/research",
            json={"symbol": "BTC", "trigger_reason": "DRAWDOWN_THRESHOLD"},
        )
        assert res_dd.status_code == 200
        assert res_dd.json()["volatility_impact_factor"] == 1.30

        # Low advisory confidence trigger
        res_low = await stratex_client.post(
            "/api/v1/intelligence/research",
            json={"symbol": "BTC", "trigger_reason": "LOW_ADVISORY_CONFIDENCE"},
        )
        assert res_low.status_code == 200
        assert res_low.json()["volatility_impact_factor"] == 1.20


@pytest.mark.asyncio
async def test_stratex_market_research_search_failure_with_fallback(stratex_client: AsyncClient):
    """Verify graceful partial evidence degradation when external search fails but DB has data."""
    with patch(
        "intelx.api.v1.stratex.WebSearchConnector.fetch",
        new_callable=AsyncMock,
        side_effect=ProviderError("Search engine rate limit"),
    ):
        res = await stratex_client.post(
            "/api/v1/intelligence/research",
            json={"symbol": "BTC", "trigger_reason": "MANUAL_OR_EVENT"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["findings"]["status"] == "PARTIAL_EVIDENCE"
        assert data["findings"]["external_search_status"] == "failed"


@pytest.mark.asyncio
async def test_stratex_market_research_total_failure_returns_503(stratex_client: AsyncClient):
    """Verify 503 is returned when no DB evidence exists AND search engine fails."""
    with patch(
        "intelx.api.v1.stratex.WebSearchConnector.fetch",
        new_callable=AsyncMock,
        side_effect=ProviderError("Search provider offline"),
    ):
        res = await stratex_client.post(
            "/api/v1/intelligence/research",
            json={"symbol": "UNKNOWN_UNINDEXED_COIN", "trigger_reason": "MANUAL_OR_EVENT"},
        )
        assert res.status_code == 503
        assert "Market news providers are unavailable" in res.json()["detail"]


@pytest.mark.asyncio
async def test_stratex_trigger_signal(stratex_client: AsyncClient):
    """Verify dispatching actionable trade signals to StrateX."""
    mock_dispatch = AsyncMock(
        return_value={
            "status": "DISPATCHED",
            "run_id": "run_test_123",
            "symbol": "BTC",
            "webhook": "https://stratex.trading/signals",
        }
    )

    with patch(
        "intelx.integrations.stratex_context.StratexConnector.notify_stratex_trade_signal",
        mock_dispatch,
    ):
        res = await stratex_client.post(
            "/api/v1/stratex/trigger-signal",
            json={
                "finding_text": "Massive institutional accumulation on BTC breaks resistance",
                "run_id": "run_test_123",
                "domain": "market",
                "confidence": 0.95,
                "webhook_url": "https://stratex.trading/signals",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "DISPATCHED"
        assert data["run_id"] == "run_test_123"
