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

    async def store_verified_findings_to_memora(
        self,
        run_id: str,
        objective: str,
        findings: list[Any],
        claims: list[Any],
        sources: list[Any],
        namespace: str = "memora://intelx/verified_facts",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Store only verified, provenance-preserving research facts into Memora.

        Strictly rejects ungrounded inferences, disputed propositions, or claims lacking valid source provenance.
        """
        settings = get_settings()
        sources_map = {str(getattr(s, "id", "") or (s.get("id") if isinstance(s, dict) else "")): s for s in sources}
        claims_map = {str(getattr(c, "id", "") or (c.get("id") if isinstance(c, dict) else "")): c for c in claims}

        verified_facts: list[dict[str, Any]] = []

        for f in findings:
            conclusion = getattr(f, "statement", None) or getattr(f, "conclusion", "") or (f.get("statement") or f.get("conclusion", "") if isinstance(f, dict) else "")
            status = str(getattr(f, "status", "verified") or (f.get("status", "verified") if isinstance(f, dict) else "verified")).lower()
            conf = getattr(f, "confidence", None) or getattr(f, "confidence_score", 0.8) or (f.get("confidence") or f.get("confidence_score", 0.8) if isinstance(f, dict) else 0.8)
            claim_ids = getattr(f, "claim_ids", None) or getattr(f, "claim_ids_json", []) or (f.get("claim_ids") or f.get("claim_ids_json", []) if isinstance(f, dict) else [])
            is_inference = getattr(f, "is_inference", False) or (f.get("is_inference", False) if isinstance(f, dict) else False) or status in ("inference", "unverified")

            # 1. Gate check: must be verified, non-inference, non-disputed, confidence >= 0.70
            if is_inference or status in ("inference", "unverified", "disputed") or float(conf) < 0.70:
                logger.info(f"Memora writeback gate skipped unverified/inference finding: '{conclusion[:40]}'")
                continue

            # 2. Gate check: must have at least 1 verified backing claim with complete provenance
            provenance: list[dict[str, Any]] = []
            for cid in claim_ids:
                claim = claims_map.get(str(cid))
                if not claim:
                    continue
                c_status = str(getattr(claim, "status", "ACTIVE") or (claim.get("status", "ACTIVE") if isinstance(claim, dict) else "ACTIVE")).upper()
                if c_status != "ACTIVE":
                    continue

                sid = str(getattr(claim, "source_id", "") or (claim.get("source_id", "") if isinstance(claim, dict) else ""))
                src = sources_map.get(sid)
                quote = getattr(claim, "quote", "") or (claim.get("quote", "") if isinstance(claim, dict) else "")
                span_start = getattr(claim, "span_start", 0) or (claim.get("span_start", 0) if isinstance(claim, dict) else 0)
                span_end = getattr(claim, "span_end", 0) or (claim.get("span_end", 0) if isinstance(claim, dict) else 0)
                doc_id = getattr(claim, "document_id", "") or (claim.get("document_id", "") if isinstance(claim, dict) else "")

                # Redact quote
                redacted_quote, _ = redact_document_text_preserving_length(quote)
                provenance.append({
                    "claim_id": str(cid),
                    "claim_text": getattr(claim, "text", "") or (claim.get("text", "") if isinstance(claim, dict) else ""),
                    "quote": redacted_quote,
                    "span_start": span_start,
                    "span_end": span_end,
                    "document_id": doc_id,
                    "source_id": sid,
                    "source_url": getattr(src, "location", getattr(src, "url", "")) if src else "",
                    "source_title": getattr(src, "title", "Source Document") if src else "Source Document",
                    "publisher": getattr(src, "publisher", None) if src else None,
                })

            if not provenance:
                logger.warning(f"Memora writeback gate rejected finding lacking valid claim provenance: '{conclusion[:40]}'")
                continue

            redacted_conclusion, _ = redact_document_text_preserving_length(conclusion)
            verified_facts.append({
                "finding_id": getattr(f, "id", None) or getattr(f, "finding_id", f"f-{len(verified_facts)+1}") or (f.get("finding_id") if isinstance(f, dict) else f"f-{len(verified_facts)+1}"),
                "conclusion": redacted_conclusion,
                "confidence": float(conf),
                "provenance_chain": provenance,
            })

        if not verified_facts:
            logger.info("Memora writeback gate: 0 verified facts met strict provenance standards. Writeback aborted.")
            return {
                "status": "rejected_no_verified_facts",
                "run_id": run_id,
                "accepted_count": 0,
                "namespace": namespace,
            }

        payload = {
            "namespace": namespace,
            "key": f"research_verified_{run_id}",
            "content": {
                "run_id": run_id,
                "objective": objective,
                "verified_facts_count": len(verified_facts),
                "facts": verified_facts,
                "tags": tags or ["intelx", "verified_evidence", "provenance_locked"],
            },
        }

        if settings.MOCK_MODE or not self.api_key:
            logger.info(f"[Memora Mock] Stored {len(verified_facts)} verified facts for run {run_id} in {namespace}")
            return {
                "status": "stored_mock",
                "namespace": namespace,
                "run_id": run_id,
                "accepted_count": len(verified_facts),
                "facts": verified_facts,
            }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{self.base_url}/api/v1/memory/items", json=payload, headers=headers)
                if resp.status_code < 300:
                    logger.info(f"Successfully published {len(verified_facts)} verified facts to Memora: {run_id}")
                    return {
                        "status": "stored",
                        "accepted_count": len(verified_facts),
                        "run_id": run_id,
                        "response": resp.json(),
                    }
                logger.warning(f"Memora returned status {resp.status_code}: {resp.text}")
                return {"status": "failed_upstream", "status_code": resp.status_code}
        except Exception as e:
            logger.warning(f"Failed to communicate with Memora: {e}")
            return {"status": "error", "error": str(e)}


async def store_verified_findings_to_memora(
    findings: list[Any],
    claims: list[Any] | None = None,
    sources: list[Any] | None = None,
    run_id: str = "run-default",
    objective: str = "Research objective",
    memora_client: Any = None,
    min_confidence: float = 0.70,
    namespace: str = "memora://intelx/verified_facts",
    tags: list[str] | None = None,
) -> int | dict[str, Any]:
    """Module-level gate for writing verified findings with provenance to Memora."""
    client = memora_client or MemoraMemoryClient()
    if not isinstance(client, MemoraMemoryClient):
        accepted = 0
        for f in findings:
            stmt = f.get("statement", "") if isinstance(f, dict) else getattr(f, "statement", "")
            conf = f.get("confidence", 0.0) if isinstance(f, dict) else getattr(f, "confidence", 0.0)
            status = str(f.get("status", "verified") if isinstance(f, dict) else getattr(f, "status", "verified")).lower()
            claim_ids = f.get("claim_ids", []) if isinstance(f, dict) else getattr(f, "claim_ids", [])
            if float(conf) >= min_confidence and status == "verified" and len(claim_ids) > 0:
                redacted, _ = redact_document_text_preserving_length(stmt)
                await client.store_memory(
                    run_id=run_id,
                    content=redacted,
                    category="verified_research",
                    tags=tags or ["intelx", "verified_evidence"],
                )
                accepted += 1
        return accepted

    res = await client.store_verified_findings_to_memora(
        run_id=run_id,
        objective=objective,
        findings=findings,
        claims=claims or [],
        sources=sources or [],
        namespace=namespace,
        tags=tags,
    )
    return res.get("accepted_count", 0) if isinstance(res, dict) else 0


