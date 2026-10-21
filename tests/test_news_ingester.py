"""Comprehensive unit and integration tests for NewsIngester and feed parser."""

import asyncio
from datetime import UTC, datetime

import pytest

from intelx.db.session import get_sessionmaker
from intelx.ingestion.news_ingester import (
    NewsIngester,
    _chunk_text,
    _fingerprint,
    _ingest_article,
    _parse_feed,
    _parse_iso_date,
    _parse_rss_date,
    _strip_html,
)


def test_strip_html_and_unescape():
    """Verify HTML tag removal and HTML entity unescaping."""
    raw = "<p>Crypto volatility reaches <b>5.2%</b> on &quot;Binance&quot; &amp; others.</p>"
    clean = _strip_html(raw)
    assert clean == 'Crypto volatility reaches 5.2% on "Binance" & others.'
    assert _strip_html("") == ""
    assert _strip_html(None) == ""


def test_date_parsers():
    """Verify RFC 2822 RSS and ISO 8601 date parsing."""
    # 1. RSS RFC 2822
    rss_str = "Wed, 21 Oct 2026 07:15:00 GMT"
    dt_rss = _parse_rss_date(rss_str)
    assert dt_rss is not None
    assert dt_rss.year == 2026
    assert dt_rss.month == 10
    assert dt_rss.day == 21

    # Invalid / None returns None
    assert _parse_rss_date("not-a-valid-date") is None
    assert _parse_rss_date(None) is None

    # 2. ISO 8601
    iso_str = "2026-10-21T07:15:00Z"
    dt_iso = _parse_iso_date(iso_str)
    assert dt_iso is not None
    assert dt_iso.year == 2026
    assert dt_iso.month == 10

    assert _parse_iso_date("bad-iso-date") is None
    assert _parse_iso_date(None) is None


def test_fingerprint_normalization():
    """Verify URL fingerprinting generates consistent SHA-256 hashes."""
    url1 = "https://example.com/news/article-101"
    url2 = "https://example.com/news/article-101"
    url3 = "https://example.com/news/article-102"

    fp1 = _fingerprint(url1)
    fp2 = _fingerprint(url2)
    fp3 = _fingerprint(url3)

    assert fp1 == fp2
    assert fp1 != fp3
    assert len(fp1) == 64


def test_chunk_text_boundaries():
    """Verify text chunking preserves word boundaries and creates sequential chunks."""
    short_text = "Short text under single chunk threshold."
    chunks_short = _chunk_text(short_text)
    assert len(chunks_short) == 1
    assert chunks_short[0] == short_text

    long_text = "Paragraph one with several words.\n\n" * 150
    chunks_long = _chunk_text(long_text)
    assert len(chunks_long) > 1
    for chunk in chunks_long:
        assert len(chunk) > 0


def test_parse_feed_rss_and_atom():
    """Verify parsing of RSS 2.0 and Atom XML feeds."""
    feed_config = {
        "publisher": "CoinDesk",
        "agent": "stratex",
        "category": "crypto_trading",
    }

    # 1. RSS 2.0 Feed
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>CoinDesk Crypto Feed</title>
        <item>
          <title>Bitcoin cross 100k milestone</title>
          <link>https://coindesk.com/article/btc-100k</link>
          <description>&lt;p&gt;Institutional inflows drive record pricing.&lt;/p&gt;</description>
          <pubDate>Wed, 21 Oct 2026 07:15:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    items_rss = _parse_feed(rss_xml, feed_config)
    assert len(items_rss) == 1
    item = items_rss[0]
    assert item["title"] == "Bitcoin cross 100k milestone"
    assert item["url"] == "https://coindesk.com/article/btc-100k"
    assert "Institutional inflows" in item["summary"]
    assert item["agent"] == "stratex"
    assert item["publisher"] == "CoinDesk"

    # 2. Atom Feed
    atom_xml = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Sentinel CVE Alerts</title>
      <entry>
        <title>CVE-2026-9999 Linux Kernel Vulnerability</title>
        <link href="https://nvd.nist.gov/vuln/detail/CVE-2026-9999"/>
        <summary>Heap buffer overflow in network packet subsystem.</summary>
        <updated>2026-10-21T08:00:00Z</updated>
      </entry>
    </feed>
    """
    atom_config = {
        "publisher": "NVD",
        "agent": "sentinel",
        "category": "security_advisories",
    }
    items_atom = _parse_feed(atom_xml, atom_config)
    assert len(items_atom) == 1
    atom_item = items_atom[0]
    assert atom_item["title"] == "CVE-2026-9999 Linux Kernel Vulnerability"
    assert atom_item["url"] == "https://nvd.nist.gov/vuln/detail/CVE-2026-9999"
    assert atom_item["agent"] == "sentinel"


@pytest.mark.asyncio
async def test_ingest_article_and_deduplication():
    """Verify database persistence of article Source, Document, and Chunks, with deduplication."""
    sessionmaker = get_sessionmaker()
    article = {
        "url": "https://reuters.com/business/finance/ecb-rate-cut-2026-10-21/",
        "title": "ECB signals further interest rate reductions",
        "summary": "Central bank macroeconomic forecast update.",
        "published_at": datetime.now(UTC),
        "publisher": "Reuters",
        "agent": "futuris",
        "category": "macro_forecasts",
    }
    full_text = "Full article body detailing macroeconomic conditions and central bank projections."

    async with sessionmaker() as session:
        # First ingestion -> True
        ingested = await _ingest_article(session, article, full_text)
        assert ingested is True
        await session.commit()

        # Second ingestion with identical URL -> deduplicated -> False
        second_ingested = await _ingest_article(session, article, full_text)
        assert second_ingested is False


@pytest.mark.asyncio
async def test_news_ingester_lifecycle():
    """Verify NewsIngester start, running state, and stop."""
    ingester = NewsIngester(interval_seconds=0.1)
    assert not ingester._running

    await ingester.start()
    assert ingester._running

    # Idempotent start
    await ingester.start()
    assert ingester._running

    await asyncio.sleep(0.05)
    await ingester.stop()
    assert not ingester._running
