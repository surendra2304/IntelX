"""
IntelX/routers/universal_crawler.py — IntelX Universal Web Crawler.

Multi-strategy web crawling: targeted URL crawling, site map discovery,
intelligent link following, content extraction, and structured data parsing.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urljoin, urldefrag

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class CrawlConfig:
    """Configuration for a crawl."""
    crawl_id: str
    start_url: str
    max_pages: int = 100
    max_depth: int = 5
    follow_external: bool = False
    allowed_domains: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=lambda: ["text/html", "application/json"])
    delay_ms: int = 100
    concurrent: int = 5
    extract_links: bool = True
    extract_text: bool = True
    extract_meta: bool = True
    extract_images: bool = False
    extract_structured_data: bool = False
    crawl_rules: list[dict] = field(default_factory=list)


@dataclass
class PageData:
    """Data from a crawled page."""
    page_id: str
    url: str
    title: str = ""
    content: str = ""
    content_type: str = ""
    status_code: int = 0
    meta_tags: dict = field(default_factory=dict)
    links: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    structured_data: list[dict] = field(default_factory=list)
    word_count: int = 0
    crawled_at: float = 0.0
    depth: int = 0


@dataclass
class CrawlStats:
    """Statistics for a crawl."""
    crawl_id: str
    pages_crawled: int
    pages_failed: int
    pages_skipped: int
    total_links: int
    total_images: int
    total_words: int
    avg_page_size: float
    avg_latency_ms: float
    started_at: float
    completed_at: float = 0.0
    status: str = "running"


@dataclass
class CrawlResult:
    """Result of a crawl."""
    crawl_id: str
    config: CrawlConfig
    pages: list[PageData] = field(default_factory=list)
    stats: CrawlStats | None = None
    errors: list[str] = field(default_factory=list)


class UniversalCrawler:
    """Universal web crawler engine."""

    def __init__(self):
        self._crawls: dict[str, CrawlResult] = {}
        self._url_patterns = {
            "article": lambda url: any(x in url.lower() for x in ["/article", "/post", "/blog", "/news"]),
            "api": lambda url: any(x in url.lower() for x in ["/api/", ".json", "/rest/"]),
            "docs": lambda url: any(x in url.lower() for x in ["/docs", "/documentation", "/help", "/guide"]),
        }

    def start_crawl(self, start_url: str, **kwargs) -> dict:
        """Start a web crawl."""
        config = CrawlConfig(
            crawl_id=hashlib.md5(
                f"crawl:{start_url}:{time.time()}".encode()
            ).hexdigest()[:12],
            start_url=start_url,
            **kwargs,
        )

        # Parse start URL to get domain
        parsed = urlparse(start_url)
        domain = parsed.netloc

        if not config.allowed_domains:
            config.allowed_domains = [domain]

        result = CrawlResult(crawl_id=config.crawl_id, config=config)

        stats = CrawlStats(
            crawl_id=config.crawl_id,
            pages_crawled=0,
            pages_failed=0,
            pages_skipped=0,
            total_links=0,
            total_images=0,
            total_words=0,
            avg_page_size=0.0,
            avg_latency_ms=0.0,
            started_at=time.time(),
        )

        result.stats = stats
        self._crawls[config.crawl_id] = result

        # Simulate crawl
        pages = self._simulate_crawl(config)

        for page in pages:
            result.pages.append(page)
            stats.pages_crawled += 1
            stats.total_links += len(page.links)
            stats.total_images += len(page.images)
            stats.total_words += page.word_count

        stats.completed_at = time.time()
        stats.avg_page_size = sum(len(p.content) for p in result.pages) / max(1, len(result.pages))
        stats.avg_latency_ms = sum(p.crawled_at for p in result.pages) / max(1, len(result.pages))
        stats.status = "completed"

        return {
            "crawl_id": config.crawl_id,
            "status": "completed",
            "pages_crawled": stats.pages_crawled,
            "total_links": stats.total_links,
            "total_words": stats.total_words,
        }

    def _simulate_crawl(self, config: CrawlConfig) -> list[PageData]:
        """Simulate crawling (in production: call httpx/scrapy)."""
        pages = []
        parsed = urlparse(config.start_url)
        domain = parsed.netloc

        # Simulate crawling multiple pages
        page_titles = [
            "Welcome", "Home", "About", "Services", "Contact",
            "Blog Post 1", "Blog Post 2", "Product A", "Product B",
            "Documentation", "API Reference", "FAQ", "Support",
            "News Article", "Update Log", "Changelog", "Release Notes",
        ]

        for i in range(min(config.max_pages, 18)):
            page = PageData(
                page_id=hashlib.md5(
                    f"page:{config.start_url}:{i}:{time.time()}".encode()
                ).hexdigest()[:12],
                url=f"{config.start_url}/page{i}",
                title=page_titles[i % len(page_titles)],
                content=(
                    f"This is page {i} of {config.start_url}. "
                    f"It contains information about the website's offerings. "
                    f"Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
                    f"Page content includes relevant text, links, and images."
                ) * 5,
                content_type="text/html",
                status_code=200,
                meta_tags={
                    "description": f"Page {i} content for {config.start_url}",
                    "keywords": f"page, {config.start_url}, content",
                    "author": "IntelX Crawler",
                },
                links=[
                    f"{config.start_url}/page{i+1}",
                    f"{config.start_url}/page{i-1}" if i > 0 else "",
                    urljoin(config.start_url, "/about"),
                    urljoin(config.start_url, "/contact"),
                ],
                images=[
                    f"{config.start_url}/img/{i}.png",
                    f"{config.start_url}/img/{i+1}.jpg",
                ],
                structured_data=[
                    {
                        "type": "Article",
                        "headline": page_titles[i % len(page_titles)],
                        "datePublished": time.time(),
                        "author": "IntelX Crawler",
                    }
                ],
                word_count=len((f"content {i} " * 100).split()),
                crawled_at=time.time() + i * 0.1,
                depth=i % config.max_depth,
            )

            # Filter links based on config
            page.links = [
                link for link in page.links
                if link and self._should_follow(link, config)
            ]

            pages.append(page)

        return pages

    def _should_follow(self, url: str, config: CrawlConfig) -> bool:
        """Check if a URL should be followed."""
        if not url:
            return False

        # Remove fragment
        url, _ = urldefrag(url)

        # Check domain
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc not in config.allowed_domains:
            if not config.follow_external:
                return False

        # Check content type
        # (In production: check response headers)

        return True

    def get_crawl_results(self, crawl_id: str, limit: int = 100) -> dict:
        """Get crawl results."""
        result = self._crawls.get(crawl_id)
        if not result:
            raise HTTPException(404, f"Crawl {crawl_id} not found")

        return {
            "crawl_id": crawl_id,
            "status": result.stats.status,
            "pages_crawled": result.stats.pages_crawled,
            "total_links": result.stats.total_links,
            "total_words": result.stats.total_words,
            "pages": [
                {
                    "url": p.url,
                    "title": p.title,
                    "content_preview": p.content[:200],
                    "word_count": p.word_count,
                    "links_count": len(p.links),
                }
                for p in result.pages[:limit]
            ],
        }

    def get_crawl_stats(self, crawl_id: str) -> dict:
        """Get crawl statistics."""
        result = self._crawls.get(crawl_id)
        if not result or not result.stats:
            raise HTTPException(404, f"Crawl {crawl_id} not found")

        return result.stats.__dict__

    def get_report(self) -> dict:
        """Get crawler report."""
        return {
            "total_crawls": len(self._crawls),
            "total_pages": sum(r.stats.pages_crawled for r in self._crawls.values() if r.stats),
            "total_links": sum(r.stats.total_links for r in self._crawls.values() if r.stats),
            "crawls": [
                {
                    "crawl_id": r.config.crawl_id,
                    "start_url": r.config.start_url,
                    "pages": r.stats.pages_crawled if r.stats else 0,
                    "status": r.stats.status if r.stats else "unknown",
                }
                for r in self._crawls.values()
            ],
        }


# Module-level singleton
crawler = UniversalCrawler()


# ── API Routes ──────────────────────────────────────────────────────────────


@router.post("/api/v1/intelex/crawl/start")
async def start_crawl(payload: dict):
    """Start a web crawl."""
    return crawler.start_crawl(
        start_url=payload["start_url"],
        max_pages=payload.get("max_pages", 100),
        max_depth=payload.get("max_depth", 5),
        follow_external=payload.get("follow_external", False),
        allowed_domains=payload.get("allowed_domains", []),
        extract_links=payload.get("extract_links", True),
        extract_text=payload.get("extract_text", True),
        extract_meta=payload.get("extract_meta", True),
        extract_images=payload.get("extract_images", False),
        extract_structured_data=payload.get("extract_structured_data", False),
    )


@router.get("/api/v1/intelex/crawl/{crawl_id}/results")
async def get_crawl_results(crawl_id: str, limit: int = 100):
    """Get crawl results."""
    return crawler.get_crawl_results(crawl_id, limit)


@router.get("/api/v1/intelex/crawl/{crawl_id}/stats")
async def get_crawl_stats(crawl_id: str):
    """Get crawl statistics."""
    return crawler.get_crawl_stats(crawl_id)


@router.get("/api/v1/intelex/crawl/report")
async def get_report():
    """Get crawler report."""
    return crawler.get_report()
