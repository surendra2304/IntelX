from types import SimpleNamespace

import pytest

from intelx.integrations import memora_context


@pytest.mark.asyncio
async def test_research_memory_uses_intelx_key_and_current_memora_api(monkeypatch):
    captured = {}
    settings = SimpleNamespace(
        MEMORA_URL="https://memora.invalid",
        INTELX_API_KEY="intelx-agent-key",
        MOCK_MODE=False,
    )
    monkeypatch.setattr(memora_context, "get_settings", lambda: settings)

    class Response:
        status_code = 201
        def json(self):
            return {"id": "memory-1"}

    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return False
        async def post(self, url, *, json, headers):
            captured.update(url=url, payload=json, headers=headers)
            return Response()

    monkeypatch.setattr(memora_context.httpx, "AsyncClient", lambda **_kwargs: Client())
    client = memora_context.MemoraMemoryClient()
    result = await client.store_research_memory("run-1", "market scan", "verified summary", 4, 2)

    assert result["status"] == "stored"
    assert result["cloud"] is True
    assert captured["url"] == "https://memora.invalid/v1/memories"
    assert captured["headers"]["Authorization"] == "Bearer intelx-agent-key"
    assert captured["headers"]["X-Agent-Name"] == "intelx"
    assert captured["payload"]["target_namespace_path"] == "memora://intelx/private"
    assert '"summary": "verified summary"' in captured["payload"]["content_text"]


@pytest.mark.asyncio
async def test_missing_intelx_memora_key_is_blocked_not_reported_as_mock(monkeypatch):
    settings = SimpleNamespace(MEMORA_URL="https://memora.invalid", INTELX_API_KEY="", MOCK_MODE=False)
    monkeypatch.setattr(memora_context, "get_settings", lambda: settings)
    result = await memora_context.MemoraMemoryClient().store_research_memory(
        "run-2", "market scan", "summary", 1, 1
    )
    assert result["status"] == "blocked_missing_credentials"
    assert result["cloud"] is False
