"""INTELX — Continuous News Ingestion Engine.

Continuously crawls RSS/Atom feeds from major news sources (tech, finance, world, sports),
fetches article content, deduplicates by URL fingerprint, and indexes everything directly
into the IntelX knowledge base (sources + documents + chunks) so it is instantly searchable.

Covers:
- Past:    already stored in DB from previous crawl cycles
- Present: crawled continuously every few minutes from live feeds
- Future:  upcoming announcements, scheduled events, product launches published in feeds
"""

import asyncio
import hashlib
import html
import logging
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import SourceKind, TrustTier
from intelx.db.models import Chunk, Document, Source
from intelx.db.session import get_sessionmaker

logger = logging.getLogger("intelx.news_ingester")

# ---------------------------------------------------------------------------
# News Feed Sources — covering tech, finance, world news, sports
# ---------------------------------------------------------------------------

NEWS_FEEDS: list[dict[str, str]] = [
    # Technology
    {"url": "https://feeds.feedburner.com/TechCrunch", "publisher": "TechCrunch", "category": "technology"},
    {"url": "https://www.theverge.com/rss/index.xml", "publisher": "The Verge", "category": "technology"},
    {"url": "https://www.wired.com/feed/rss", "publisher": "Wired", "category": "technology"},
    {"url": "https://feeds.arstechnica.com/arstechnica/index", "publisher": "Ars Technica", "category": "technology"},
    {"url": "https://venturebeat.com/feed/", "publisher": "VentureBeat", "category": "technology"},
    {"url": "https://www.engadget.com/rss.xml", "publisher": "Engadget", "category": "technology"},
    {"url": "https://9to5mac.com/feed/", "publisher": "9to5Mac", "category": "technology"},
    {"url": "https://www.gsmarena.com/rss-news-reviews.php3", "publisher": "GSMArena", "category": "technology"},
    {"url": "https://www.91mobiles.com/feed/", "publisher": "91Mobiles", "category": "technology"},
    # Finance & Markets
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline", "publisher": "Yahoo Finance", "category": "finance"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "publisher": "CNBC", "category": "finance"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "publisher": "Bloomberg Markets", "category": "finance"},
    {"url": "https://www.marketwatch.com/rss/topstories", "publisher": "MarketWatch", "category": "finance"},
    # World News
    {"url": "http://feeds.bbci.co.uk/news/rss.xml", "publisher": "BBC News", "category": "world"},
    {"url": "https://feeds.reuters.com/reuters/topNews", "publisher": "Reuters", "category": "world"},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml", "publisher": "Al Jazeera", "category": "world"},
    {"url": "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms", "publisher": "Times of India", "category": "world"},
    {"url": "https://indianexpress.com/section/india/feed/", "publisher": "Indian Express", "category": "world"},
    # Science
    {"url": "https://www.nature.com/nature.rss", "publisher": "Nature", "category": "science"},
    {"url": "https://feeds.newscientist.com/full-feed", "publisher": "New Scientist", "category": "science"},
    # Crypto
    {"url": "https://cointelegraph.com/rss", "publisher": "CoinTelegraph", "category": "crypto"},
    {"url": "https://coindesk.com/arc/outboundfeeds/rss/", "publisher": "CoinDesk", "category": "crypto"},
]

CRAWL_INTERVAL_SECONDS = 300  # 5 minutes per cycle
MAX_ITEMS_PER_FEED = 30
MAX_ARTICLE_BYTES = 512_000   # 500 KB
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


# ---------------------------------------------------------------------------
# XML / RSS Parsing utilities
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities from a string."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_rss_datetime(date_str: str | None) -> datetime | None:
    """Parse RFC-2822 date string into timezone-aware datetime."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _parse_iso_datetime(date_str: str | None) -> datetime | None:
    """Parse ISO-8601 date string into timezone-aware datetime."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _fingerprint(url: str) -> str:
    """SHA-256 fingerprint of a URL for deduplication."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk_words = words[i:i + chunk_size]
        chunks.append(" ".join(chunk_words))
        i += chunk_size - overlap
    return chunks or [text[:chunk_size]]


# ---------------------------------------------------------------------------
# RSS / Atom Feed Parser
# ---------------------------------------------------------------------------

def _parse_feed_xml(xml_text: str, publisher: str, category: str) -> list[dict[str, Any]]:
    """Parse RSS/Atom XML into a list of article dicts."""
    items: list[dict[str, Any]] = []

    # Detect Atom vs RSS
    is_atom = "<feed" in xml_text[:500]

    if is_atom:
        # Atom feed
        entries = re.findall(r"<entry>(.*?)</entry>", xml_text, re.DOTALL)
        for entry in entries[:MAX_ITEMS_PER_FEED]:
            title_m = re.search(r"<title[^>]*>(.*?)</title>", entry, re.DOTALL)
            link_m = re.search(r'<link[^>]+href=["\']([^"\']+)["\']', entry)
            if not link_m:
                link_m = re.search(r"<link>(.*?)</link>", entry, re.DOTALL)
            summary_m = re.search(r"<summary[^>]*>(.*?)</summary>", entry, re.DOTALL) or \
                        re.search(r"<content[^>]*>(.*?)</content>", entry, re.DOTALL)
            updated_m = re.search(r"<updated>(.*?)</updated>", entry)
            published_m = re.search(r"<published>(.*?)</published>", entry)

            url = _strip_html(link_m.group(1) if link_m else "")
            if not url or not url.startswith("http"):
                continue

            items.append({
                "url": url,
                "title": _strip_html(title_m.group(1)) if title_m else "Untitled",
                "summary": _strip_html(summary_m.group(1)) if summary_m else "",
                "published_at": _parse_iso_datetime(published_m.group(1) if published_m else None) or
                                _parse_iso_datetime(updated_m.group(1) if updated_m else None),
                "publisher": publisher,
                "category": category,
            })
    else:
        # RSS feed
        items_xml = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
        for item in items_xml[:MAX_ITEMS_PER_FEED]:
            title_m = re.search(r"<title[^>]*>(.*?)</title>", item, re.DOTALL)
            link_m = re.search(r"<link>(.*?)</link>", item, re.DOTALL)
            if not link_m:
                link_m = re.search(r'<link[^>]+href=["\']([^"\']+)["\']', item)
            desc_m = re.search(r"<description[^>]*>(.*?)</description>", item, re.DOTALL)
            pubdate_m = re.search(r"<pubDate>(.*?)</pubDate>", item)

            url = _strip_html(link_m.group(1) if link_m else "").strip()
            if not url or not url.startswith("http"):
                continue

            items.append({
                "url": url,
                "title": _strip_html(title_m.group(1)) if title_m else "Untitled",
                "summary": _strip_html(desc_m.group(1)) if desc_m else "",
                "published_at": _parse_rss_datetime(pubdate_m.group(1) if pubdate_m else None),
                "publisher": publisher,
                "category": category,
            })

    return items


# ---------------------------------------------------------------------------
# Article full-text fetcher
# ---------------------------------------------------------------------------

async def _fetch_article_text(client: httpx.AsyncClient, url: str) -> str:
    """Fetch and extract main readable text from an article URL."""
    try:
        resp = await client.get(url, timeout=10.0, follow_redirects=True)
        if resp.status_code != 200:
            return ""
        content = resp.text[:MAX_ARTICLE_BYTES]

        # Extract <article>, <main>, or <body> content
        for tag in ("article", "main", "body"):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", content, re.DOTALL | re.IGNORECASE)
            if m:
                return _strip_html(m.group(1))

        return _strip_html(content)
    except Exception as ex:
        logger.debug(f"Could not fetch article {url}: {ex}")
        return ""


# ---------------------------------------------------------------------------
# Ingestion into IntelX DB
# ---------------------------------------------------------------------------

async def _ingest_article(session: AsyncSession, article: dict[str, Any], full_text: str) -> bool:
    """Ingest a single article into sources + documents + chunks. Returns True if new."""
    url = article["url"]
    fp = _fingerprint(url)

    # Deduplication: skip if already ingested
    existing = await session.execute(select(Source).where(Source.fingerprint == fp))
    if existing.scalar_one_or_none():
        return False

    domain = urlparse(url).netloc or article["publisher"]
    text_body = full_text.strip() or article["summary"]
    if not text_body:
        return False

    # Build full document text: Title + category + summary + body
    full_doc = (
        f"[{article['category'].upper()}] {article['title']}\n"
        f"Source: {article['publisher']} | {url}\n"
        f"Published: {article['published_at'].isoformat() if article['published_at'] else 'Unknown'}\n\n"
        f"{text_body}"
    )

    source = Source(
        kind=SourceKind.WEB,
        location=url,
        domain=domain,
        publisher=article["publisher"],
        title=article["title"],
        published_at=article["published_at"],
        retrieved_at=datetime.now(UTC),
        content_type="text/html",
        fingerprint=fp,
        trust_tier=TrustTier.LIKELY_RELIABLE,
        robots_ok=True,
        injection_risk=False,
    )
    session.add(source)
    await session.flush()

    doc = Document(
        source_id=source.id,
        text=full_doc,
        language="en",
    )
    session.add(doc)
    await session.flush()

    # Chunk the document for FTS indexing
    chunks = _chunk_text(full_doc)
    for idx, chunk_text in enumerate(chunks):
        chunk = Chunk(
            document_id=doc.id,
            text=chunk_text,
            idx=idx,
            start_char=0,
            end_char=len(chunk_text),
        )
        session.add(chunk)

    return True


# ---------------------------------------------------------------------------
# Main Ingestion Loop
# ---------------------------------------------------------------------------

async def crawl_once(session_factory: Any | None = None) -> dict[str, int]:
    """Run one full crawl cycle across all configured news feeds."""
    factory = session_factory or get_sessionmaker()
    stats = {"feeds_crawled": 0, "articles_new": 0, "articles_skipped": 0, "errors": 0}

    headers = {
        "User-Agent": "IntelX-NewsBot/2.0 (https://intelx-3cz1.onrender.com)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }

    async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
        for feed_config in NEWS_FEEDS:
            feed_url = feed_config["url"]
            publisher = feed_config["publisher"]
            category = feed_config["category"]
            try:
                resp = await client.get(feed_url)
                if resp.status_code != 200:
                    logger.warning(f"Feed {feed_url} returned {resp.status_code}")
                    stats["errors"] += 1
                    continue

                articles = _parse_feed_xml(resp.text, publisher, category)
                stats["feeds_crawled"] += 1

                for article in articles:
                    try:
                        # Quick dedup check without full fetch
                        fp = _fingerprint(article["url"])
                        async with factory() as session:
                            existing = await session.execute(
                                select(Source).where(Source.fingerprint == fp)
                            )
                            if existing.scalar_one_or_none():
                                stats["articles_skipped"] += 1
                                continue

                        # Fetch full article text
                        full_text = await _fetch_article_text(client, article["url"])

                        async with factory() as session:
                            is_new = await _ingest_article(session, article, full_text)
                            await session.commit()
                            if is_new:
                                stats["articles_new"] += 1
                                logger.info(f"Ingested: [{category}] {article['title'][:80]}")
                            else:
                                stats["articles_skipped"] += 1

                    except Exception as ex:
                        logger.warning(f"Error ingesting article {article.get('url', '?')}: {ex}")
                        stats["errors"] += 1

            except Exception as ex:
                logger.warning(f"Error crawling feed {feed_url}: {ex}")
                stats["errors"] += 1

    logger.info(
        f"[NewsIngester] Cycle complete — "
        f"feeds={stats['feeds_crawled']}, new={stats['articles_new']}, "
        f"skipped={stats['articles_skipped']}, errors={stats['errors']}"
    )
    return stats


class NewsIngester:
    """Continuously crawls all configured news feeds in a background asyncio loop."""

    def __init__(self, interval_seconds: float = CRAWL_INTERVAL_SECONDS) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    async def _loop(self) -> None:
        logger.info(f"[NewsIngester] Starting continuous news ingestion (every {self.interval_seconds}s).")
        # Run first cycle immediately on boot
        while self._running:
            try:
                await crawl_once()
            except Exception as ex:
                logger.error(f"[NewsIngester] Unexpected error in crawl loop: {ex}", exc_info=True)
            if self._running:
                await asyncio.sleep(self.interval_seconds)

    async def start(self) -> None:
        """Start the background ingestion loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[NewsIngester] Background ingestion task created.")

    async def stop(self) -> None:
        """Stop the background ingestion loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("[NewsIngester] Stopped.")
