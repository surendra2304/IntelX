"""Tests for SearXNG Search Connector, multi-source routing, and HTML extraction."""

import httpx
import pytest

from intelx.connectors.search import (
    SearXNGSearchConnector,
    WebSearchConnector,
)
from intelx.core.errors import ProviderError
from intelx.core.settings import Settings
from intelx.memory.normalize import chunk_text_with_offsets, normalize_text_content


@pytest.mark.asyncio
async def test_searxng_empty_base_url():
    """SearXNG connector returns empty list when no base URL is provided."""
    connector = SearXNGSearchConnector(base_url=None)
    results = await connector.fetch("query")
    assert results == []


@pytest.mark.asyncio
async def test_searxng_search_successful_parse():
    """SearXNG connector parses json results accurately."""
    mock_response_data = {
        "results": [
            {
                "url": "https://example.com/page1",
                "title": "Example Page 1",
                "content": "This is content from page 1",
            },
            {
                "url": "https://example.com/page2",
                "title": "Example Page 2",
                "content": "This is snippet from page 2",
            },
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert "format=json" in str(request.url)
        assert "q=synthetic+biology" in str(request.url)
        return httpx.Response(200, json=mock_response_data)

    transport = httpx.MockTransport(mock_handler)
    connector = SearXNGSearchConnector(base_url="http://searxng:8080", transport=transport)
    results = await connector.fetch("synthetic biology", max_results=5)

    assert len(results) == 2
    assert results[0].url == "https://example.com/page1"
    assert results[0].title == "Example Page 1"
    assert results[0].snippet == "This is content from page 1"


@pytest.mark.asyncio
async def test_searxng_search_error_handling():
    """SearXNG connector wraps HTTP failure in ProviderError."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    transport = httpx.MockTransport(mock_handler)
    connector = SearXNGSearchConnector(base_url="http://searxng:8080", transport=transport)

    with pytest.raises(ProviderError) as exc_info:
        await connector.fetch("query")
    assert "searxng" in exc_info.value.details.get("provider", "")


@pytest.mark.asyncio
async def test_web_search_searxng_fallback():
    """WebSearchConnector prioritizes SearXNG when configured and no Tavily key is set."""
    mock_response_data = {
        "results": [
            {
                "url": "https://searxng.result/1",
                "title": "SearXNG Hit",
                "content": "Relevant content snippet",
            }
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_response_data)

    transport = httpx.MockTransport(mock_handler)
    settings = Settings(
        _env_file=None,
        MOCK_MODE=False,
        TAVILY_API_KEY=None,
        SEARXNG_URL="http://searxng:8080",
    )
    router = WebSearchConnector(settings=settings, transport=transport)
    results = await router.fetch("energy density")

    assert len(results) >= 1
    assert results[0].url == "https://searxng.result/1"
    assert results[0].title == "SearXNG Hit"


def test_html_article_extraction_prioritization():
    """Verify HTML extraction isolates article container when substantial content is present."""
    html_doc = b"""
    <!DOCTYPE html>
    <html>
    <head><title>News Site</title></head>
    <body>
        <nav><a href="/home">Home</a><a href="/about">About</a></nav>
        <header><h1>Site Header Banner</h1></header>
        <aside><h3>Sidebar Advertisements and Clickbait</h3></aside>
        <article>
            <h2>Breakthrough in Solid-State Electrolytes</h2>
            <p>Researchers at the National Energy Laboratory have synthesized a novel sulfide-based solid electrolyte with ionic conductivity exceeding 25 mS/cm at 25 degrees Celsius.</p>
            <p>The battery retained 92% capacity after 1,000 continuous charge-discharge cycles without dendrite shorting.</p>
        </article>
        <footer><p>&copy; 2026 Tech News Corp. All rights reserved.</p></footer>
    </body>
    </html>
    """
    extracted = normalize_text_content(html_doc, "text/html")
    assert "Breakthrough in Solid-State Electrolytes" in extracted
    assert "ionic conductivity exceeding 25 mS/cm" in extracted
    assert "Sidebar Advertisements" not in extracted
    assert "Site Header Banner" not in extracted
    assert "All rights reserved" not in extracted


def test_chunking_with_offsets_invariants():
    """Verify chunk_text_with_offsets guarantees strict character boundary continuity."""
    sample_text = (
        "Paragraph 1 discusses the fundamental physics of quantum annealing.\n\n"
        "Paragraph 2 evaluates experimental decoherence times across superconducting qubits.\n\n"
        "Paragraph 3 summarizes the empirical benchmark against classical simulated annealing.\n\n"
        "Paragraph 4 outlines future architecture scaling to 5,000 connected flux qubits."
    )
    chunks = chunk_text_with_offsets(sample_text, target_size=100, overlap=20)
    assert len(chunks) > 1

    for chunk in chunks:
        # Guarantee exact substring slicing
        assert sample_text[chunk.start_char : chunk.end_char] == chunk.text
        assert chunk.end_char > chunk.start_char
