"""Signed durable Memora event publishing for IntelX research notifications."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

import httpx

from intelx.core.settings import get_settings


async def publish_research_notice(
    *,
    target_agent: str,
    run_id: str,
    finding_summary: str,
    category: str,
    domain: str,
    confidence: float,
    recommended_targets: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Persist a small, idempotent IntelX notice; it does not claim task completion."""
    settings = get_settings()
    production = settings.ENV.lower() == "production" or os.getenv("ENVIRONMENT", "").lower() == "production"
    if not production and os.getenv("INTELX_MEMORA_EVENTS_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return {"status": "disabled"}
    if settings.MOCK_MODE:
        return {"status": "skipped_mock"}
    key = settings.INTELX_API_KEY
    if not key:
        return {"status": "blocked_missing_credential"}

    target = target_agent.lower().strip()
    event_id = f"intelx-{run_id}-{target}"[:128]
    envelope = {
        "message_id": event_id,
        "correlation_id": f"corr_{uuid.uuid4().hex[:16]}",
        "from_agent": "intelx",
        "to_agent": target,
        "intent": "intelx.news",
        "priority": "high" if category in {"actionable_trade_signal", "regulatory_change", "emerging_threat"} else "normal",
        "ttl": 3600,
        "auth_token": None,
        "payload": {
            "signal_id": run_id,
            "headline": finding_summary[:500],
            "summary": finding_summary[:2000],
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "relevance": {"category": category, "confidence": confidence, "domain": domain},
            "topics": recommended_targets or [],
        },
        "created_at": time.time(),
    }
    signed = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    envelope["signature"] = hmac.new(key.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    url = f"{settings.MEMORA_URL.rstrip('/')}/mesh/envelope"
    try:
        if client:
            response = await client.post(url, json=envelope, headers=headers, timeout=8.0)
        else:
            async with httpx.AsyncClient(timeout=8.0) as http_client:
                response = await http_client.post(url, json=envelope, headers=headers)
        if response.status_code == 202:
            data = response.json()
            return {"status": data.get("status", "accepted"), "event_id": data.get("event_id"), "cursor": data.get("cursor")}
        return {"status": "failed_upstream", "status_code": response.status_code}
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}
