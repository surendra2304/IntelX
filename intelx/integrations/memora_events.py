"""Signed durable Memora event publishing for IntelX research notifications."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from intelx.core.settings import get_settings

_PUBLISH_ATTEMPTS = 3
_PUBLISH_BASE_DELAY_SECONDS = 0.25


def _public_source_refs(sources: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Keep only bounded, public HTTP(S) provenance suitable for agent notices."""
    refs: list[dict[str, str]] = []
    for source in (sources or [])[:20]:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or source.get("source_url") or "").strip()
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            continue
        if parsed.username or parsed.password:
            continue
        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            continue
        try:
            if not ipaddress.ip_address(hostname).is_global:
                continue
        except ValueError:
            pass
        ref = {"url": url[:2048]}
        for field, limit in (
            ("title", 300),
            ("domain", 255),
            ("publisher", 255),
            ("published_at", 64),
            ("trust_tier", 32),
        ):
            value = source.get(field)
            if value is not None and str(value).strip():
                ref[field] = str(value).strip()[:limit]
        refs.append(ref)
    return refs


async def publish_research_notice(
    *,
    target_agent: str,
    run_id: str,
    finding_summary: str,
    category: str,
    domain: str,
    confidence: float,
    recommended_targets: list[str] | None = None,
    sources: list[dict[str, Any]] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Persist a small, idempotent IntelX notice; it does not claim task completion."""
    settings = get_settings()
    production = (
        settings.ENV.lower() == "production" or os.getenv("ENVIRONMENT", "").lower() == "production"
    )
    if not production and os.getenv("INTELX_MEMORA_EVENTS_ENABLED", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        return {"status": "disabled"}
    if settings.MOCK_MODE:
        return {"status": "skipped_mock"}
    key = settings.INTELX_API_KEY
    if not key:
        return {"status": "blocked_missing_credential"}

    target = target_agent.lower().strip()
    event_id = f"intelx-{run_id}-{target}"[:128]
    source_refs = _public_source_refs(sources)
    event_payload = {
        "signal_id": run_id,
        "headline": finding_summary[:500],
        "summary": finding_summary[:2000],
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "relevance": {"category": category, "confidence": confidence, "domain": domain},
        "topics": recommended_targets or [],
    }
    if source_refs:
        event_payload["source_url"] = source_refs[0]["url"]
        event_payload["sources"] = source_refs

    envelope = {
        "message_id": event_id,
        # Keep retries byte-for-byte stable so the receiver can deduplicate them.
        "correlation_id": f"corr_{hashlib.sha256(event_id.encode()).hexdigest()[:16]}",
        "from_agent": "intelx",
        "to_agent": target,
        "intent": "intelx.news",
        "priority": "high"
        if category in {"actionable_trade_signal", "regulatory_change", "emerging_threat"}
        else "normal",
        "ttl": 3600,
        "auth_token": None,
        "payload": event_payload,
        "created_at": time.time(),
    }
    signed = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    envelope["signature"] = hmac.new(key.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    url = f"{settings.MEMORA_URL.rstrip('/')}/mesh/envelope"
    async def post_once(http_client: httpx.AsyncClient) -> httpx.Response:
        return await http_client.post(url, json=envelope, headers=headers, timeout=8.0)

    async def deliver(http_client: httpx.AsyncClient) -> dict[str, Any]:
        for attempt in range(_PUBLISH_ATTEMPTS):
            try:
                response = await post_once(http_client)
            except httpx.TransportError as exc:
                if attempt + 1 == _PUBLISH_ATTEMPTS:
                    return {"status": "error", "error": type(exc).__name__}
            else:
                if response.status_code == 202:
                    data = response.json()
                    return {
                        "status": data.get("status", "accepted"),
                        "event_id": data.get("event_id"),
                        "cursor": data.get("cursor"),
                    }
                # Retry transient throttling and server failures only. Auth, policy,
                # validation, and other client errors need configuration changes.
                if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
                    return {"status": "failed_upstream", "status_code": response.status_code}
                if attempt + 1 == _PUBLISH_ATTEMPTS:
                    return {"status": "failed_upstream", "status_code": response.status_code}

            await asyncio.sleep(_PUBLISH_BASE_DELAY_SECONDS * (2**attempt))
        return {"status": "error", "error": "retry_exhausted"}

    try:
        if client:
            return await deliver(client)
        async with httpx.AsyncClient(timeout=8.0) as http_client:
            return await deliver(http_client)
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}
