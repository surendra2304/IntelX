import hashlib
from datetime import UTC, datetime

import pytest

from intelx.ingestion import news_ingester


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement):
        class _Result:
            @staticmethod
            def scalar_one_or_none():
                return None

        return _Result()

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_new_feed_article_is_broadcast_once_after_successful_ingestion(monkeypatch):
    article = {
        "url": "https://exchange.example/notices/123",
        "title": "Exchange publishes a market notice",
        "summary": "A sourced headline summary.",
        "published_at": datetime(2026, 9, 27, tzinfo=UTC),
        "publisher": "Example Exchange",
        "agent": "stratex",
        "category": "crypto_trading",
    }
    captured = []
    monkeypatch.setattr(
        news_ingester,
        "FRIDAY_UNIVERSE_FEEDS",
        [
            {
                "url": "https://feed.example/rss",
                **{k: article[k] for k in ("publisher", "agent", "category")},
            }
        ],
    )
    monkeypatch.setattr(news_ingester, "get_sessionmaker", lambda: lambda: _Session())
    monkeypatch.setattr(news_ingester, "_parse_feed", lambda *_args: [article])
    monkeypatch.setattr(
        news_ingester, "_fetch_article_text", lambda *_args: _async_value("Fetched source text.")
    )
    monkeypatch.setattr(news_ingester, "_ingest_article", lambda *_args: _async_value(True))

    async def publish(**kwargs):
        captured.append(kwargs)
        return {"status": "accepted", "event_id": "event-1"}

    monkeypatch.setattr(news_ingester, "publish_research_notice", publish)

    class _Fetcher:
        async def fetch(self, _url, **_kwargs):
            return type("FetchResult", (), {"status_code": 200, "content": b"<rss/>"})()

    monkeypatch.setattr(news_ingester, "HttpFetchConnector", _Fetcher)

    stats = await news_ingester.crawl_once()

    assert stats["articles_new"] == 1
    assert len(captured) == 1
    notice = captured[0]
    assert notice["target_agent"] == "all"
    fingerprint = news_ingester._fingerprint(article["url"])
    expected_digest = hashlib.sha256(fingerprint.encode()).hexdigest()
    assert notice["run_id"] == f"news-stratex-{expected_digest}"
    assert notice["category"] == "crypto_trading"
    assert notice["recommended_targets"] == ["stratex"]
    assert notice["sources"][0]["url"] == article["url"]
    assert "not been independently verified" in notice["finding_summary"]


async def _async_value(value):
    return value
