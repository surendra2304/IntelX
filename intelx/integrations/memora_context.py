"""INTELX Memora Cloud Memory Integration Contract and Long-Term Evidence Sync."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from intelx.core.security import redact_document_text_preserving_length
from intelx.core.settings import get_settings

logger = logging.getLogger("intelx.integrations.memora")


class MemoraMemoryClient:
    """Publishes synthesized research summaries and verified evidence metadata to Memora."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self.base_url = base_url or settings.MEMORA_URL or "https://memora-9zr9.onrender.com"
        self.api_key = api_key or settings.MEMORA_API_KEY

    async def store_research_memory(
        self,
        run_id: str,
        objective: str,
        summary: str,
        evidence_count: int,
        claims_count: int,
        namespace: str = "memora://intelx/private",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Store redacted research findings into Memora long-term memory."""
        settings = get_settings()

        # Enforce non-destructive secret scrubber before memory export
        redacted_summary, _ = redact_document_text_preserving_length(summary)

        payload = {
            "namespace": namespace,
            "key": f"research_run_{run_id}",
            "content": {
                "run_id": run_id,
                "objective": objective,
                "summary": redacted_summary,
                "evidence_count": evidence_count,
                "claims_count": claims_count,
                "tags": tags or ["intelx", "research", "evidence"],
            },
        }

        if settings.MOCK_MODE or not self.api_key:
            logger.info(f"[Memora Mock] Stored research memory for run {run_id} in {namespace}")
            return {"status": "stored_mock", "namespace": namespace, "run_id": run_id}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{self.base_url}/api/v1/memory/items", json=payload, headers=headers)
                if resp.status_code < 300:
                    logger.info(f"Successfully published research memory to Memora: {run_id}")
                    return resp.json()
                logger.warning(f"Memora returned status {resp.status_code}: {resp.text}")
                return {"status": "failed_upstream", "status_code": resp.status_code}
        except Exception as e:
            logger.warning(f"Failed to communicate with Memora: {e}")
            return {"status": "error", "error": str(e)}
