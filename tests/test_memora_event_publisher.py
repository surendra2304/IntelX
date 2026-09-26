import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest

from intelx.integrations import memora_events


@pytest.mark.asyncio
async def test_intelx_publishes_signed_idempotent_recipient_notice(monkeypatch):
    captured = {}
    settings = SimpleNamespace(
        ENV="development",
        MOCK_MODE=False,
        INTELX_API_KEY="intelx-test-key",
        MEMORA_URL="https://memora.invalid",
    )
    monkeypatch.setattr(memora_events, "get_settings", lambda: settings)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("INTELX_MEMORA_EVENTS_ENABLED", "true")

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["envelope"] = json.loads(request.content)
        return httpx.Response(202, json={"status": "accepted", "event_id": "intelx-run-1-futuris", "cursor": 12})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await memora_events.publish_research_notice(
            target_agent="all",
            run_id="run-1",
            finding_summary="Verified market event",
            category="actionable_trade_signal",
            domain="market",
            confidence=0.9,
            client=client,
        )

    assert result == {"status": "accepted", "event_id": "intelx-run-1-futuris", "cursor": 12}
    assert captured["url"] == "https://memora.invalid/mesh/envelope"
    assert captured["authorization"] == "Bearer intelx-test-key"
    envelope = captured["envelope"]
    signature = envelope.pop("signature")
    signed = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str).encode()
    expected = hmac.new(b"intelx-test-key", signed, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(signature, expected)
    assert envelope["to_agent"] == "all"
    assert envelope["intent"] == "intelx.news"
