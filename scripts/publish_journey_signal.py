"""Publish one real IntelX feed item to Memora's durable mesh under a journey correlation ID.

Fetches a configured RSS feed live (real news), takes the newest item, and
publishes it through the same signed, idempotent path NewsIngester uses —
with an explicit correlation_id so a single journey can thread every hop.

Usage:
    python scripts/publish_journey_signal.py --correlation-id corrJ [--feed-index 0]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from intelx.integrations.memora_events import publish_research_notice
from intelx.ingestion.news_ingester import FRIDAY_UNIVERSE_FEEDS, _parse_feed


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--correlation-id", required=True, help="Journey correlation ID threaded to every hop")
    parser.add_argument("--feed-index", type=int, default=0, help="Index into NewsIngester's FRIDAY_UNIVERSE_FEEDS")
    args = parser.parse_args()

    # Non-production publishing requires the explicit events flag.
    os.environ.setdefault("INTELX_MEMORA_EVENTS_ENABLED", "true")
    feed = FRIDAY_UNIVERSE_FEEDS[args.feed_index]

    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(feed["url"], timeout=15.0)
        if response.status_code != 200:
            print(json.dumps({"status": "feed_fetch_failed", "status_code": response.status_code, "feed": feed["url"]}))
            return 1
        items = _parse_feed(response.text, feed)

    if not items:
        print(json.dumps({"status": "no_items", "feed": feed["url"]}))
        return 1
    item = items[0]

    summary = f"{item['title']} — {(item.get('summary') or '').strip()[:400]}"
    receipt = await publish_research_notice(
        target_agent="all",
        run_id=f"journey-{args.correlation_id}",
        finding_summary=summary,
        category=item["category"],
        domain="intelx.news",
        # Neutral relevance placeholder; not a truth probability.
        confidence=0.5,
        recommended_targets=[feed["agent"]],
        sources=[
            {
                "title": item["title"],
                "url": item["url"],
                "domain": urlparse(item["url"]).netloc,
                "publisher": item["publisher"],
                "published_at": item["published_at"].isoformat() if item.get("published_at") else None,
                "trust_tier": "LIKELY_RELIABLE",
            }
        ],
        correlation_id=args.correlation_id,
    )

    print(
        json.dumps(
            {
                "status": receipt.get("status"),
                "event_id": receipt.get("event_id"),
                "cursor": receipt.get("cursor"),
                "correlation_id": args.correlation_id,
                "headline": item["title"][:160],
                "publisher": item["publisher"],
                "feed": feed["url"],
            }
        )
    )
    return 0 if receipt.get("status") == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
