"""Tests for Tavily Search Connector and UnifiedSearchConnector priority integration."""

import httpx
import pytest

from intelx.connectors.search import (
    TavilySearchConnector,
    WebSearchConnector,
)
from intelx.core.errors import ProviderError
from intelx.core.settings import Settings


@pytest.mark.asyncio
async def test_tavily_connector_empty_key():
    """Verify Tavily connector returns empty results when no API key configured."""
    connector = TavilySearchConnector(api_key=None)
    results = await connector.fetch("test query")
    assert results == []


@pytest.mark.asyncio
async def test_tavily_connector_success_mock_transport():
    """Verify Tavily connector parses structured search responses."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.tavily.com/search"
        data = {
            "results": [
                {
                    "url": "https://example.com/ai-research",
                    "title": "AI Research Breakthrough",
                    "content": "A major breakthrough in autonomous multi-agent intelligence was announced.",
                },
                {
                    "url": "https://example.com/battery-tech",
                    "title": "Solid State Battery Testing",
                    "content": "Energy density reached 450 Wh/kg in independent evaluations.",
                },
            ]
        }
        return httpx.Response(200, json=data)

    transport = httpx.MockTransport(mock_handler)
    connector = TavilySearchConnector(api_key="tvly-mock-key-12345", transport=transport)
    results = await connector.fetch("autonomous AI and batteries", max_results=5)

    assert len(results) == 2
    assert results[0].title == "AI Research Breakthrough"
    assert results[0].url == "https://example.com/ai-research"
    assert "450 Wh/kg" in results[1].snippet


@pytest.mark.asyncio
async def test_tavily_connector_http_error():
    """Verify Tavily connector raises ProviderError on HTTP errors."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Invalid API key"})

    transport = httpx.MockTransport(mock_handler)
    connector = TavilySearchConnector(api_key="tvly-bad-key", transport=transport)

    with pytest.raises(ProviderError) as exc_info:
        await connector.fetch("query")

    assert "tavily" in str(exc_info.value).lower()
    assert exc_info.value.details.get("status_code") == 401


@pytest.mark.asyncio
async def test_tavily_connector_network_exception():
    """Verify Tavily connector wraps transport exceptions in ProviderError."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out")

    transport = httpx.MockTransport(mock_handler)
    connector = TavilySearchConnector(api_key="tvly-timeout-key", transport=transport)

    with pytest.raises(ProviderError) as exc_info:
        await connector.fetch("query")

    assert "tavily" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_unified_search_prioritizes_tavily():
    """Verify UnifiedSearchConnector executes Tavily first when TAVILY_API_KEY is configured."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if "tavily.com" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": "https://tavily.com/result-1",
                            "title": "Tavily Primary Result",
                            "content": "Primary search results returned from Tavily AI search.",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    settings = Settings(
        INTELX_MOCK_MODE=False,
        TAVILY_API_KEY="tvly-valid-key",
        SEARXNG_URL=None,
    )

    connector = WebSearchConnector(settings=settings, transport=transport)
    results = await connector.fetch("quantum computing breakthroughs")

    assert len(results) >= 1
    assert results[0].url == "https://tavily.com/result-1"
    assert results[0].title == "Tavily Primary Result"
