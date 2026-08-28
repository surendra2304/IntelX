"""INTELX Search Connectors (Tavily, DuckDuckGo HTML, Mock)."""

import json
import logging
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bs4
import httpx

from intelx.connectors.base import BaseConnector
from intelx.core.settings import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Standardized search engine result entry."""

    url: str
    title: str
    snippet: str


class TavilySearchConnector(BaseConnector):
    """Tavily search API integration."""

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(
            name="tavily_search",
            capabilities=["web_search", "structured_snippets"],
            required_credentials=["TAVILY_API_KEY"],
            classification="EXTERNAL_SEARCH",
            **kwargs,
        )
        self.api_key = api_key

    async def fetch(self, target: str, **kwargs: Any) -> list[SearchResult]:
        """Execute search query against Tavily API."""
        if not self.api_key:
            return []

        max_results = kwargs.get("max_results", 10)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": target,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", []):
                results.append(
                    SearchResult(
                        url=item.get("url", ""),
                        title=item.get("title", ""),
                        snippet=item.get("content", ""),
                    )
                )
            return results


class DuckDuckGoSearchConnector(BaseConnector):
    """HTML scraper for DuckDuckGo public search (graceful fallback)."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, **kwargs: Any) -> None:
        super().__init__(
            name="duckduckgo_search",
            capabilities=["web_search", "unauthenticated"],
            required_credentials=[],
            classification="EXTERNAL_SEARCH",
            **kwargs,
        )
        self._transport = transport

    async def fetch(self, target: str, **kwargs: Any) -> list[SearchResult]:
        """Scrape DuckDuckGo HTML search results capped at 10."""
        max_results = min(kwargs.get("max_results", 10), 10)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(target)}"

        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=10.0, headers=headers
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"DuckDuckGo returned HTTP {resp.status_code}")
                    return []

                soup = bs4.BeautifulSoup(resp.text, "html.parser")
                results: list[SearchResult] = []

                for result_div in soup.find_all("div", class_="result", limit=max_results):
                    title_tag = result_div.find("a", class_="result__a")
                    snippet_tag = result_div.find("a", class_="result__snippet")

                    if title_tag:
                        href = title_tag.get("href", "")
                        if "/l/?uddg=" in href:
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                            actual_url = parsed.get("uddg", [href])[0]
                        else:
                            actual_url = href

                        snippet_text = snippet_tag.get_text(strip=True) if snippet_tag else ""
                        results.append(
                            SearchResult(
                                url=actual_url,
                                title=title_tag.get_text(strip=True),
                                snippet=snippet_text,
                            )
                        )
                        if len(results) >= max_results:
                            break

                return results
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed gracefully: {e}")
            return []


class WebSearchConnector(BaseConnector):
    """Router connector selecting Tavily, DuckDuckGo, or deterministic Mock fixtures."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="web_search",
            capabilities=["web_search"],
            required_credentials=[],
            classification="EXTERNAL_SEARCH",
            **kwargs,
        )
        self.settings = settings or get_settings()
        self._tavily = TavilySearchConnector(api_key=self.settings.TAVILY_API_KEY)
        self._ddg = DuckDuckGoSearchConnector(transport=transport)
        self._fixtures_dir = Path("./tests/fixtures/search_results").resolve()

    def _load_mock_results(self, query: str) -> list[SearchResult]:
        """Load canned mock search results from fixture files or generate deterministic entries."""
        safe_name = "".join(c if c.isalnum() else "_" for c in query.lower())[:30]
        fixture_file = self._fixtures_dir / f"{safe_name}.json"

        if fixture_file.exists():
            try:
                data = json.loads(fixture_file.read_text(encoding="utf-8"))
                return [SearchResult(**item) for item in data]
            except Exception as e:
                logger.warning(f"Failed loading search fixture {fixture_file}: {e}")

        # Deterministic fallback mock search results
        return [
            SearchResult(
                url=f"https://en.wikipedia.org/wiki/{urllib.parse.quote(query[:20])}",
                title=f"{query.title()} - Comprehensive Technical Overview",
                snippet=(
                    f"Authoritative technical reference regarding {query}. "
                    "Details core methodologies, empirical evaluations, and benchmarks."
                ),
            ),
            SearchResult(
                url=f"https://arxiv.org/abs/2608.{abs(hash(query)) % 90000 + 10000}",
                title=f"Recent Breakthroughs in {query.title()}",
                snippet=(
                    f"Experimental evaluation of state-of-the-art architectures in {query}. "
                    "Demonstrating verified improvements over established baselines."
                ),
            ),
            SearchResult(
                url=f"https://nature.com/articles/s41586-2026-{abs(hash(query)) % 5000}",
                title=f"Scalability and Industry Impact of {query.title()}",
                snippet=(
                    f"Peer-reviewed survey documenting industrial parameters for {query}. "
                    "Highlighting supply chain integration and long-term durability metrics."
                ),
            ),
        ]

    async def fetch(self, target: str, **kwargs: Any) -> list[SearchResult]:
        """Execute search across active or mock provider."""
        if self.settings.MOCK_MODE:
            return self._load_mock_results(target)

        if self.settings.TAVILY_API_KEY:
            results = await self._tavily.fetch(target, **kwargs)
            if results:
                return results

        return await self._ddg.fetch(target, **kwargs)
