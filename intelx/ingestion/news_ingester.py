"""INTELX — FRIDAY Universe Intelligence Ingestion Engine.

Collects targeted intelligence for all 9 FRIDAY Universe agents:

  Stratex   → Crypto prices, Binance signals, trading news, market moves
  Futuris   → Economic forecasts, macro trends, upcoming events, earnings
  Sentinel  → CVEs, security advisories, breach reports, threat intel
  FRIDAY    → AI/LLM news, product launches, world events, announcements
  Cortex    → Web trends, competitor moves, marketing intelligence
  Forge     → Dev tools, GitHub releases, framework updates, APIs
  Inference → AI model releases, research papers, benchmarks
  Memora    → N/A (memory store, no external feeds needed)
  IntelX    → Self-improvement: research methodology news

All feeds are curated for signal quality — no noise, only actionable intel.
Deduplication by URL fingerprint. Runs every 5 minutes, 24/7.
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

from intelx.core.enums import SourceKind, TrustTier
from intelx.db.models import Chunk, Document, Source
from intelx.db.session import get_sessionmaker

logger = logging.getLogger("intelx.ingester")

# ---------------------------------------------------------------------------
# FRIDAY Universe — Targeted Intelligence Feeds per Agent
# ---------------------------------------------------------------------------

FRIDAY_UNIVERSE_FEEDS: list[dict[str, str]] = [

    # ── STRATEX: Crypto & Algorithmic Trading ──────────────────────────────
    # Stratex runs Binance Futures 24/7. Needs price movements, whale alerts,
    # exchange news, regulatory actions, upcoming token events.
    {"url": "https://cointelegraph.com/rss",
     "publisher": "CoinTelegraph", "agent": "stratex", "category": "crypto_trading"},
    {"url": "https://coindesk.com/arc/outboundfeeds/rss/",
     "publisher": "CoinDesk", "agent": "stratex", "category": "crypto_trading"},
    {"url": "https://cryptopanic.com/news/rss/",
     "publisher": "CryptoPanic", "agent": "stratex", "category": "crypto_trading"},
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=json",
     "publisher": "CoinDesk Markets", "agent": "stratex", "category": "crypto_trading"},
    {"url": "https://decrypt.co/feed",
     "publisher": "Decrypt", "agent": "stratex", "category": "crypto_trading"},
    {"url": "https://bitcoinmagazine.com/.rss/full/",
     "publisher": "Bitcoin Magazine", "agent": "stratex", "category": "crypto_trading"},
    {"url": "https://www.theblock.co/rss.xml",
     "publisher": "The Block", "agent": "stratex", "category": "crypto_trading"},

    # ── FUTURIS: Forecasting & Market Macro ───────────────────────────────
    # Futuris builds probabilistic forecasts. Needs economic data, earnings
    # calendars, macro shifts, analyst forecasts, upcoming events.
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
     "publisher": "CNBC Markets", "agent": "futuris", "category": "macro_economics"},
    {"url": "https://www.marketwatch.com/rss/topstories",
     "publisher": "MarketWatch", "agent": "futuris", "category": "macro_economics"},
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline",
     "publisher": "Yahoo Finance", "agent": "futuris", "category": "macro_economics"},
    {"url": "https://www.economist.com/finance-and-economics/rss.xml",
     "publisher": "The Economist", "agent": "futuris", "category": "macro_economics"},
    {"url": "https://www.ft.com/rss/home",
     "publisher": "Financial Times", "agent": "futuris", "category": "macro_economics"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss",
     "publisher": "Bloomberg", "agent": "futuris", "category": "macro_economics"},
    {"url": "https://www.investing.com/rss/news.rss",
     "publisher": "Investing.com", "agent": "futuris", "category": "macro_economics"},

    # ── SENTINEL: Cybersecurity Threat Intelligence ────────────────────────
    # Sentinel is the security shield. Needs CVE alerts, breach reports,
    # malware campaigns, zero-days, threat actor activities.
    {"url": "https://feeds.feedburner.com/TheHackersNews",
     "publisher": "The Hacker News", "agent": "sentinel", "category": "cybersecurity"},
    {"url": "https://www.bleepingcomputer.com/feed/",
     "publisher": "BleepingComputer", "agent": "sentinel", "category": "cybersecurity"},
    {"url": "https://krebsonsecurity.com/feed/",
     "publisher": "Krebs on Security", "agent": "sentinel", "category": "cybersecurity"},
    {"url": "https://www.darkreading.com/rss.xml",
     "publisher": "Dark Reading", "agent": "sentinel", "category": "cybersecurity"},
    {"url": "https://www.securityweek.com/feed",
     "publisher": "SecurityWeek", "agent": "sentinel", "category": "cybersecurity"},
    {"url": "https://isc.sans.edu/rssfeed_full.xml",
     "publisher": "SANS ISC", "agent": "sentinel", "category": "cybersecurity"},
    {"url": "https://nvd.nist.gov/feeds/json/cve/1.1/nvdcve-1.1-recent.meta",
     "publisher": "NIST NVD CVEs", "agent": "sentinel", "category": "cybersecurity"},

    # ── FRIDAY (Master Orchestrator): AI, World, Tech Announcements ────────
    # FRIDAY is the central OS assistant. Needs general AI news, product
    # launches, world events, government actions, upcoming announcements.
    {"url": "https://feeds.feedburner.com/TechCrunch",
     "publisher": "TechCrunch", "agent": "friday", "category": "ai_tech"},
    {"url": "https://www.theverge.com/rss/index.xml",
     "publisher": "The Verge", "agent": "friday", "category": "ai_tech"},
    {"url": "https://venturebeat.com/feed/",
     "publisher": "VentureBeat AI", "agent": "friday", "category": "ai_tech"},
    {"url": "https://www.wired.com/feed/rss",
     "publisher": "Wired", "agent": "friday", "category": "ai_tech"},
    {"url": "http://feeds.bbci.co.uk/news/rss.xml",
     "publisher": "BBC News", "agent": "friday", "category": "world_events"},
    {"url": "https://feeds.reuters.com/reuters/topNews",
     "publisher": "Reuters", "agent": "friday", "category": "world_events"},
    {"url": "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",
     "publisher": "Times of India", "agent": "friday", "category": "world_events"},
    {"url": "https://www.gsmarena.com/rss-news-reviews.php3",
     "publisher": "GSMArena", "agent": "friday", "category": "product_launches"},
    {"url": "https://www.91mobiles.com/feed/",
     "publisher": "91Mobiles", "agent": "friday", "category": "product_launches"},
    {"url": "https://www.engadget.com/rss.xml",
     "publisher": "Engadget", "agent": "friday", "category": "product_launches"},

    # ── CORTEX: Web Intelligence & Trends ─────────────────────────────────
    # Cortex does web operations and lead qualification.
    # Needs digital marketing trends, SEO changes, business news.
    {"url": "https://searchengineland.com/feed",
     "publisher": "Search Engine Land", "agent": "cortex", "category": "web_intelligence"},
    {"url": "https://techcrunch.com/startups/feed/",
     "publisher": "TechCrunch Startups", "agent": "cortex", "category": "web_intelligence"},
    {"url": "https://www.producthunt.com/feed",
     "publisher": "Product Hunt", "agent": "cortex", "category": "web_intelligence"},

    # ── FORGE: Software Engineering & Dev Tools ────────────────────────────
    # Forge builds software autonomously. Needs framework releases,
    # language updates, GitHub trending, dev tools, API changes.
    {"url": "https://feeds.arstechnica.com/arstechnica/index",
     "publisher": "Ars Technica", "agent": "forge", "category": "software_dev"},
    {"url": "https://github.blog/feed/",
     "publisher": "GitHub Blog", "agent": "forge", "category": "software_dev"},
    {"url": "https://www.infoq.com/feed/?variant=rss",
     "publisher": "InfoQ", "agent": "forge", "category": "software_dev"},
    {"url": "https://feeds.feedburner.com/ThePythonRange",
     "publisher": "Python News", "agent": "forge", "category": "software_dev"},
    {"url": "https://simonwillison.net/atom/everything/",
     "publisher": "Simon Willison", "agent": "forge", "category": "software_dev"},

    # ── INFERENCE: AI Research & Model Updates ─────────────────────────────
    # Inference is the LLM gateway. Needs model releases, benchmarks,
    # provider changes, pricing updates, new API capabilities.
    {"url": "https://openai.com/blog/rss.xml",
     "publisher": "OpenAI Blog", "agent": "inference", "category": "ai_research"},
    {"url": "https://www.anthropic.com/news/rss.xml",
     "publisher": "Anthropic News", "agent": "inference", "category": "ai_research"},
    {"url": "https://blog.google/technology/ai/rss/",
     "publisher": "Google AI Blog", "agent": "inference", "category": "ai_research"},
    {"url": "https://huggingface.co/blog/feed.xml",
     "publisher": "Hugging Face Blog", "agent": "inference", "category": "ai_research"},
    {"url": "https://feeds.feedburner.com/aiweekly",
     "publisher": "AI Weekly", "agent": "inference", "category": "ai_research"},
    {"url": "https://export.arxiv.org/rss/cs.AI",
     "publisher": "ArXiv CS.AI", "agent": "inference", "category": "ai_research"},
    {"url": "https://export.arxiv.org/rss/cs.LG",
     "publisher": "ArXiv ML", "agent": "inference", "category": "ai_research"},
]

CRAWL_INTERVAL_SECONDS = 300   # Every 5 minutes
MAX_ITEMS_PER_FEED = 25
MAX_ARTICLE_BYTES = 400_000    # 400 KB
CHUNK_SIZE = 600
CHUNK_OVERLAP = 80


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    # First unwrap CDATA sections so content inside is preserved
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_rss_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        # Strip CDATA if present
        date_str = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", date_str, flags=re.DOTALL).strip()
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _parse_iso_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        date_str = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", date_str, flags=re.DOTALL).strip()
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _chunk_text(text: str) -> list[str]:
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk_words = words[i:i + CHUNK_SIZE]
        chunks.append(" ".join(chunk_words))
        i += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks or [text[:CHUNK_SIZE]]


# ---------------------------------------------------------------------------
# RSS / Atom parser
# ---------------------------------------------------------------------------

def _parse_feed(xml_text: str, feed_config: dict[str, str]) -> list[dict[str, Any]]:
    publisher = feed_config["publisher"]
    agent = feed_config["agent"]
    category = feed_config["category"]
    items: list[dict[str, Any]] = []

    is_atom = "<feed" in xml_text[:500]

    if is_atom:
        entries = re.findall(r"<entry[^>]*>(.*?)</entry>", xml_text, re.DOTALL)
        for entry in entries[:MAX_ITEMS_PER_FEED]:
            title_m = re.search(r"<title[^>]*>(.*?)</title>", entry, re.DOTALL)
            link_m = re.search(r'<link[^>]+href=["\']([^"\']+)["\']', entry)
            if not link_m:
                link_m = re.search(r"<link[^>]*>(.*?)</link>", entry, re.DOTALL)
            if not link_m:
                link_m = re.search(r"<id[^>]*>(.*?)</id>", entry, re.DOTALL)
            summary_m = re.search(r"<summary[^>]*>(.*?)</summary>", entry, re.DOTALL) or \
                        re.search(r"<content[^>]*>(.*?)</content>", entry, re.DOTALL)
            date_m = re.search(r"<published[^>]*>(.*?)</published>", entry, re.DOTALL) or \
                     re.search(r"<updated[^>]*>(.*?)</updated>", entry, re.DOTALL)

            url = _strip_html(link_m.group(1) if link_m else "").strip()
            if not url or not url.startswith("http"):
                continue
            items.append({
                "url": url,
                "title": _strip_html(title_m.group(1)) if title_m else "Untitled",
                "summary": _strip_html(summary_m.group(1)) if summary_m else "",
                "published_at": _parse_iso_date(date_m.group(1) if date_m else None),
                "publisher": publisher, "agent": agent, "category": category,
            })
    else:
        for item in re.findall(r"<item[^>]*>(.*?)</item>", xml_text, re.DOTALL)[:MAX_ITEMS_PER_FEED]:
            title_m = re.search(r"<title[^>]*>(.*?)</title>", item, re.DOTALL)
            link_m = re.search(r"<link[^>]*>(.*?)</link>", item, re.DOTALL)
            if not link_m:
                link_m = re.search(r'<link[^>]+href=["\']([^"\']+)["\']', item)
            if not link_m:
                link_m = re.search(r"<guid[^>]*>(.*?)</guid>", item, re.DOTALL)
            desc_m = re.search(r"<description[^>]*>(.*?)</description>", item, re.DOTALL)
            date_m = re.search(r"<pubDate[^>]*>(.*?)</pubDate>", item, re.DOTALL)

            url = _strip_html(link_m.group(1) if link_m else "").strip()
            if not url or not url.startswith("http"):
                continue
            items.append({
                "url": url,
                "title": _strip_html(title_m.group(1)) if title_m else "Untitled",
                "summary": _strip_html(desc_m.group(1)) if desc_m else "",
                "published_at": _parse_rss_date(date_m.group(1) if date_m else None),
                "publisher": publisher, "agent": agent, "category": category,
            })

    return items


async def _fetch_article_text(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url, timeout=8.0, follow_redirects=True)
        if resp.status_code != 200:
            return ""
        content = resp.text[:MAX_ARTICLE_BYTES]
        for tag in ("article", "main", "body"):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", content, re.DOTALL | re.IGNORECASE)
            if m:
                return _strip_html(m.group(1))
        return _strip_html(content)
    except Exception:
        return ""


async def _ingest_article(session: Any, article: dict[str, Any], full_text: str) -> bool:
    url = article["url"]
    fp = _fingerprint(url)

    existing = await session.execute(select(Source).where(Source.fingerprint == fp))
    if existing.scalar_one_or_none():
        return False

    text_body = full_text.strip() or article["summary"]
    if not text_body or len(text_body) < 50:
        return False

    # Build richly tagged document for search
    full_doc = (
        f"[FRIDAY_AGENT:{article['agent'].upper()}] "
        f"[CATEGORY:{article['category'].upper()}]\n"
        f"TITLE: {article['title']}\n"
        f"SOURCE: {article['publisher']} | {url}\n"
        f"PUBLISHED: {article['published_at'].isoformat() if article['published_at'] else 'Unknown'}\n\n"
        f"{text_body}"
    )

    source = Source(
        kind=SourceKind.WEB,
        location=url,
        domain=urlparse(url).netloc or article["publisher"],
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

    doc = Document(source_id=source.id, text=full_doc, language="en")
    session.add(doc)
    await session.flush()

    for idx, chunk_text in enumerate(_chunk_text(full_doc)):
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
# Main crawl cycle
# ---------------------------------------------------------------------------

async def crawl_once(session_factory: Any | None = None) -> dict[str, Any]:
    factory = session_factory or get_sessionmaker()
    stats: dict[str, Any] = {
        "feeds_crawled": 0, "articles_new": 0,
        "articles_skipped": 0, "errors": 0,
        "by_agent": {}
    }

    headers = {
        "User-Agent": "IntelX-FRIDAY-Bot/2.0 (FRIDAY Universe Intelligence Engine)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }

    async with httpx.AsyncClient(headers=headers, timeout=12.0, follow_redirects=True) as client:
        for feed_config in FRIDAY_UNIVERSE_FEEDS:
            agent = feed_config["agent"]
            feed_url = feed_config["url"]
            try:
                resp = await client.get(feed_url)
                if resp.status_code != 200:
                    stats["errors"] += 1
                    continue

                articles = _parse_feed(resp.text, feed_config)
                stats["feeds_crawled"] += 1

                for article in articles:
                    try:
                        fp = _fingerprint(article["url"])
                        async with factory() as session:
                            existing = await session.execute(
                                select(Source).where(Source.fingerprint == fp)
                            )
                            if existing.scalar_one_or_none():
                                stats["articles_skipped"] += 1
                                continue

                        full_text = await _fetch_article_text(client, article["url"])

                        async with factory() as session:
                            is_new = await _ingest_article(session, article, full_text)
                            await session.commit()

                        if is_new:
                            stats["articles_new"] += 1
                            stats["by_agent"][agent] = stats["by_agent"].get(agent, 0) + 1
                            logger.info(
                                f"[{agent.upper()}] Ingested: {article['title'][:70]}"
                            )
                        else:
                            stats["articles_skipped"] += 1

                    except Exception as ex:
                        logger.debug(f"Article error: {ex}")
                        stats["errors"] += 1

            except Exception as ex:
                logger.warning(f"Feed error {feed_url}: {ex}")
                stats["errors"] += 1

    logger.info(
        f"[NewsIngester] Cycle done — "
        f"new={stats['articles_new']}, skipped={stats['articles_skipped']}, "
        f"errors={stats['errors']} | by_agent={stats['by_agent']}"
    )
    return stats


# ---------------------------------------------------------------------------
# Background Loop
# ---------------------------------------------------------------------------

class NewsIngester:
    """Continuously crawls FRIDAY Universe targeted feeds."""

    def __init__(self, interval_seconds: float = CRAWL_INTERVAL_SECONDS) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    async def _loop(self) -> None:
        logger.info(
            f"[NewsIngester] FRIDAY Universe intelligence ingestion started "
            f"({len(FRIDAY_UNIVERSE_FEEDS)} feeds, every {self.interval_seconds}s)."
        )
        while self._running:
            try:
                await crawl_once()
            except Exception as ex:
                logger.error(f"[NewsIngester] Crawl loop error: {ex}", exc_info=True)
            if self._running:
                await asyncio.sleep(self.interval_seconds)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("[NewsIngester] Stopped.")
