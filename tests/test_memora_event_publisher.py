import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest

from intelx.integrations import memora_events
from intelx.integrations.ecosystem_dispatch import dispatch_sequentially


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
        return httpx.Response(
            202, json={"status": "accepted", "event_id": "intelx-run-1-futuris", "cursor": 12}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await memora_events.publish_research_notice(
            target_agent="all",
            run_id="run-1",
            finding_summary="Verified market event",
            category="actionable_trade_signal",
            domain="market",
            confidence=0.9,
            sources=[
                {
                    "title": "Exchange notice",
                    "url": "https://exchange.example/notices/123",
                    "domain": "exchange.example",
                    "publisher": "Example Exchange",
                    "published_at": "2026-09-26T12:00:00Z",
                    "trust_tier": "TRUSTED",
                },
                {"title": "Local secret", "url": "http://127.0.0.1/private"},
                {"title": "Credential URL", "url": "https://user:pass@example.org/report"},
            ],
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
    assert envelope["payload"]["source_url"] == "https://exchange.example/notices/123"
    assert envelope["payload"]["sources"] == [
        {
            "url": "https://exchange.example/notices/123",
            "title": "Exchange notice",
            "domain": "exchange.example",
            "publisher": "Example Exchange",
            "published_at": "2026-09-26T12:00:00Z",
            "trust_tier": "TRUSTED",
        }
    ]


def test_public_source_refs_rejects_non_public_url_shapes_and_bounds_list():
    refs = memora_events._public_source_refs(
        [
            {"url": "file:///etc/passwd"},
            {"url": "https://user:secret@example.org/news"},
            {"url": "https://news.example/item/1", "title": "x" * 500},
            *({"url": f"https://news.example/{index}"} for index in range(25)),
        ]
    )

    assert len(refs) == 18  # The input cap is 20, including two rejected entries.
    assert len(refs[0]["title"]) == 300
    assert all(ref["url"].startswith("https://news.example/") for ref in refs)


@pytest.mark.asyncio
async def test_ecosystem_deliveries_are_awaited_in_order_and_report_failures(caplog):
    import logging

    calls = []

    async def stored():
        calls.append("Memora")
        return {"status": "stored"}

    async def unavailable():
        calls.append("Futuris")
        raise TimeoutError("upstream timed out")

    async def delivered():
        calls.append("StrateX")
        return {"status": "delivered", "status_code": 202}

    result = await dispatch_sequentially(
        [("Memora", stored), ("Futuris", unavailable), ("StrateX", delivered)],
        logger=logging.getLogger("intelx.test.ecosystem"),
    )

    assert calls == ["Memora", "Futuris", "StrateX"]
    assert result == {
        "Memora": {"status": "stored"},
        "Futuris": {"status": "error", "error": "TimeoutError"},
        "StrateX": {"status": "delivered", "status_code": 202},
    }
    assert "delivery Futuris raised TimeoutError" in caplog.text


@pytest.mark.asyncio
async def test_futuris_memora_notice_receives_research_source_provenance(monkeypatch):
    from intelx.integrations import futuris_context

    captured = {}
    settings = SimpleNamespace(
        ENV="development",
        MOCK_MODE=False,
        FUTURIS_WEBHOOK_URL="https://futuris.invalid/webhook",
        FUTURIS_BASE_URL="https://futuris.invalid",
        FUTURIS_API_KEY="futuris-test-key",
    )
    monkeypatch.setattr(futuris_context, "get_settings", lambda: settings)

    async def capture_notice(**kwargs):
        captured.update(kwargs)
        return {"status": "accepted"}

    monkeypatch.setattr(memora_events, "publish_research_notice", capture_notice)
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"status": "ok"}))
    sources = [{"title": "Regulator filing", "url": "https://regulator.example/filing"}]
    async with httpx.AsyncClient(transport=transport) as client:
        result = (
            await futuris_context.ResearchTriggeredForecasting.notify_futuris_research_relevant(
                finding_text="Regulatory filing changes the market outlook",
                run_id="futuris-provenance-1",
                domain="market",
                extra_context={"sources": sources},
                client=client,
            )
        )

    assert result["status"] == "delivered"
    assert captured["target_agent"] == "all"
    assert captured["sources"] == sources


@pytest.mark.asyncio
async def test_stratex_memora_notice_receives_research_source_provenance(monkeypatch):
    from intelx.integrations import stratex_context

    captured = {}
    settings = SimpleNamespace(
        ENV="development",
        MOCK_MODE=False,
        STRATEX_WEBHOOK_URL="https://stratex.invalid/webhook",
        STRATEX_BASE_URL="https://stratex.invalid",
        STRATEX_API_KEY="stratex-test-key",
    )
    monkeypatch.setattr(stratex_context, "get_settings", lambda: settings)

    async def capture_notice(**kwargs):
        captured.update(kwargs)
        return {"status": "accepted"}

    monkeypatch.setattr(memora_events, "publish_research_notice", capture_notice)
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"status": "ok"}))
    sources = [{"title": "Exchange notice", "url": "https://exchange.example/notices/7"}]
    async with httpx.AsyncClient(transport=transport) as client:
        result = await stratex_context.StratexConnector.notify_stratex_trade_signal(
            finding_text="Exchange reports a market catalyst",
            run_id="stratex-provenance-1",
            domain="market",
            extra_context={"sources": sources},
            client=client,
        )

    assert result["status"] == "delivered"
    assert captured["target_agent"] == "all"
    assert captured["sources"] == sources
