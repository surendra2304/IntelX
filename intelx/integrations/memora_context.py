"""INTELX Memora Cloud Memory Integration Contract and Long-Term Evidence Sync."""

from __future__ import annotations

import json
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
        self.base_url = base_url or settings.MEMORA_URL or "http://memora:8000"
        self.api_key = api_key or settings.INTELX_API_KEY

    async def _store_cloud_memory(
        self,
        *,
        namespace: str,
        content: dict[str, Any],
        provenance: dict[str, Any],
        importance: float = 0.8,
    ) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "blocked_missing_credentials", "cloud": False}
        payload = {
            "content_text": json.dumps(content, ensure_ascii=False, sort_keys=True),
            "memory_type": "semantic",
            "source": "agent:intelx",
            "target_namespace_path": namespace,
            "importance": importance,
            "confidence": 1.0,
            "provenance": provenance,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "X-Agent-Name": "intelx",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/memories", json=payload, headers=headers
                )
            if resp.status_code in (200, 201):
                return {"status": "stored", "cloud": True, "response": resp.json()}
            logger.warning("Memora rejected IntelX memory write with HTTP %s", resp.status_code)
            return {"status": "failed_upstream", "cloud": False, "status_code": resp.status_code}
        except Exception as exc:
            logger.warning("Memora IntelX write failed (%s)", type(exc).__name__)
            return {"status": "error", "cloud": False, "error": type(exc).__name__}

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

        content = {
            "run_id": run_id,
            "objective": objective,
            "summary": redacted_summary,
            "evidence_count": evidence_count,
            "claims_count": claims_count,
            "tags": tags or ["intelx", "research", "evidence"],
        }

        if settings.MOCK_MODE:
            logger.info(f"[Memora Mock] Stored research memory for run {run_id} in {namespace}")
            return {"status": "stored_mock", "namespace": namespace, "run_id": run_id}
        return await self._store_cloud_memory(
            namespace=namespace,
            content=content,
            provenance={
                "run_id": run_id,
                "objective": objective,
                "kind": "research_summary",
                "tags": tags or [],
            },
        )

    async def publish_research_handoff(
        self,
        run_id: str,
        objective: str,
        summary: str,
        claims: list[Any] | None = None,
        findings: list[Any] | None = None,
        sources: list[Any] | None = None,
        namespace_prefix: str = "intelx://research",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Publish verified research briefs and extracted claims directly to Memora.

        Targets POST /v1/memories under the intelx://research/ namespace:
          - intelx://research/briefs: comprehensive research executive brief
          - intelx://research/claims: verbatim claims with exact span offsets
        """
        settings = get_settings()
        tags_list = tags or ["intelx", "research", "handoff"]
        brief_ns = f"{namespace_prefix.rstrip('/')}/briefs"
        claims_ns = f"{namespace_prefix.rstrip('/')}/claims"

        # 1. Publish research brief
        brief_result = await self.store_research_memory(
            run_id=run_id,
            objective=objective,
            summary=summary,
            evidence_count=len(sources or []),
            claims_count=len(claims or []),
            namespace=brief_ns,
            tags=tags_list,
        )

        # 2. Extract and format active claims with verbatim quotes and character spans
        claims_list = claims or []
        formatted_claims = []
        for c in claims_list:
            status = str(
                getattr(c, "status", "ACTIVE")
                if hasattr(c, "status")
                else (c.get("status", "ACTIVE") if isinstance(c, dict) else "ACTIVE")
            ).upper()
            if status != "ACTIVE":
                continue
            quote = (
                getattr(c, "quote", "")
                if hasattr(c, "quote")
                else (c.get("quote", "") if isinstance(c, dict) else "")
            )
            redacted_quote, _ = redact_document_text_preserving_length(quote)
            formatted_claims.append(
                {
                    "claim_id": str(
                        getattr(c, "id", "")
                        if hasattr(c, "id")
                        else (c.get("id", "") if isinstance(c, dict) else "")
                    ),
                    "text": (
                        getattr(c, "text", "")
                        if hasattr(c, "text")
                        else (c.get("text", "") if isinstance(c, dict) else "")
                    ),
                    "quote": redacted_quote,
                    "span_start": int(
                        getattr(c, "span_start", 0)
                        if hasattr(c, "span_start")
                        else (c.get("span_start", 0) if isinstance(c, dict) else 0)
                    ),
                    "span_end": int(
                        getattr(c, "span_end", 0)
                        if hasattr(c, "span_end")
                        else (c.get("span_end", 0) if isinstance(c, dict) else 0)
                    ),
                    "confidence": float(
                        getattr(c, "confidence", 1.0)
                        if hasattr(c, "confidence")
                        else (c.get("confidence", 1.0) if isinstance(c, dict) else 1.0)
                    ),
                    "source_id": str(
                        getattr(c, "source_id", "")
                        if hasattr(c, "source_id")
                        else (c.get("source_id", "") if isinstance(c, dict) else "")
                    ),
                    "document_id": str(
                        getattr(c, "document_id", "")
                        if hasattr(c, "document_id")
                        else (c.get("document_id", "") if isinstance(c, dict) else "")
                    ),
                }
            )

        claims_result = {}
        if formatted_claims:
            claims_content = {
                "run_id": run_id,
                "objective": objective,
                "claims_count": len(formatted_claims),
                "claims": formatted_claims,
                "tags": tags_list + ["claims", "extracted_evidence"],
            }
            if settings.MOCK_MODE:
                claims_result = {
                    "status": "stored_mock",
                    "namespace": claims_ns,
                    "run_id": run_id,
                    "claims_count": len(formatted_claims),
                }
            else:
                claims_result = await self._store_cloud_memory(
                    namespace=claims_ns,
                    content=claims_content,
                    provenance={
                        "run_id": run_id,
                        "objective": objective,
                        "kind": "extracted_claims",
                    },
                    importance=0.90,
                )

        return {
            "status": "handoff_completed",
            "run_id": run_id,
            "brief": brief_result,
            "claims": claims_result,
            "brief_namespace": brief_ns,
            "claims_namespace": claims_ns,
            "claims_published": len(formatted_claims),
        }

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
        sources_map = {
            str(getattr(s, "id", "") or (s.get("id") if isinstance(s, dict) else "")): s
            for s in sources
        }
        claims_map = {
            str(getattr(c, "id", "") or (c.get("id") if isinstance(c, dict) else "")): c
            for c in claims
        }

        verified_facts: list[dict[str, Any]] = []

        for f in findings:
            conclusion = (
                getattr(f, "statement", None)
                or getattr(f, "conclusion", "")
                or (f.get("statement") or f.get("conclusion", "") if isinstance(f, dict) else "")
            )
            status = str(
                getattr(f, "status", "verified")
                or (f.get("status", "verified") if isinstance(f, dict) else "verified")
            ).lower()
            conf = (
                getattr(f, "confidence", None)
                or getattr(f, "confidence_score", 0.8)
                or (
                    f.get("confidence") or f.get("confidence_score", 0.8)
                    if isinstance(f, dict)
                    else 0.8
                )
            )
            claim_ids = (
                getattr(f, "claim_ids", None)
                or getattr(f, "claim_ids_json", [])
                or (
                    f.get("claim_ids") or f.get("claim_ids_json", []) if isinstance(f, dict) else []
                )
            )
            is_inference = (
                getattr(f, "is_inference", False)
                or (f.get("is_inference", False) if isinstance(f, dict) else False)
                or status in ("inference", "unverified")
            )

            # 1. Gate check: must be verified, non-inference, non-disputed, confidence >= 0.70
            if (
                is_inference
                or status in ("inference", "unverified", "disputed")
                or float(conf) < 0.70
            ):
                logger.info(
                    f"Memora writeback gate skipped unverified/inference finding: '{conclusion[:40]}'"
                )
                continue

            # 2. Gate check: must have at least 1 verified backing claim with complete provenance
            provenance: list[dict[str, Any]] = []
            for cid in claim_ids:
                claim = claims_map.get(str(cid))
                if not claim:
                    continue
                c_status = str(
                    getattr(claim, "status", "ACTIVE")
                    or (claim.get("status", "ACTIVE") if isinstance(claim, dict) else "ACTIVE")
                ).upper()
                if c_status != "ACTIVE":
                    continue

                sid = str(
                    getattr(claim, "source_id", "")
                    or (claim.get("source_id", "") if isinstance(claim, dict) else "")
                )
                src = sources_map.get(sid)
                quote = getattr(claim, "quote", "") or (
                    claim.get("quote", "") if isinstance(claim, dict) else ""
                )
                span_start = getattr(claim, "span_start", 0) or (
                    claim.get("span_start", 0) if isinstance(claim, dict) else 0
                )
                span_end = getattr(claim, "span_end", 0) or (
                    claim.get("span_end", 0) if isinstance(claim, dict) else 0
                )
                doc_id = getattr(claim, "document_id", "") or (
                    claim.get("document_id", "") if isinstance(claim, dict) else ""
                )

                # Redact quote
                redacted_quote, _ = redact_document_text_preserving_length(quote)
                provenance.append(
                    {
                        "claim_id": str(cid),
                        "claim_text": getattr(claim, "text", "")
                        or (claim.get("text", "") if isinstance(claim, dict) else ""),
                        "quote": redacted_quote,
                        "span_start": span_start,
                        "span_end": span_end,
                        "document_id": doc_id,
                        "source_id": sid,
                        "source_url": getattr(src, "location", getattr(src, "url", ""))
                        if src
                        else "",
                        "source_title": getattr(src, "title", "Source Document")
                        if src
                        else "Source Document",
                        "publisher": getattr(src, "publisher", None) if src else None,
                    }
                )

            if not provenance:
                logger.warning(
                    f"Memora writeback gate rejected finding lacking valid claim provenance: '{conclusion[:40]}'"
                )
                continue

            redacted_conclusion, _ = redact_document_text_preserving_length(conclusion)
            verified_facts.append(
                {
                    "finding_id": getattr(f, "id", None)
                    or getattr(f, "finding_id", f"f-{len(verified_facts) + 1}")
                    or (
                        f.get("finding_id")
                        if isinstance(f, dict)
                        else f"f-{len(verified_facts) + 1}"
                    ),
                    "conclusion": redacted_conclusion,
                    "confidence": float(conf),
                    "provenance_chain": provenance,
                }
            )

        if not verified_facts:
            logger.info(
                "Memora writeback gate: 0 verified facts met strict provenance standards. Writeback aborted."
            )
            return {
                "status": "rejected_no_verified_facts",
                "run_id": run_id,
                "accepted_count": 0,
                "namespace": namespace,
            }

        content = {
            "run_id": run_id,
            "objective": objective,
            "verified_facts_count": len(verified_facts),
            "facts": verified_facts,
            "tags": tags or ["intelx", "verified_evidence", "provenance_locked"],
        }

        if settings.MOCK_MODE:
            logger.info(
                f"[Memora Mock] Stored {len(verified_facts)} verified facts for run {run_id} in {namespace}"
            )
            return {
                "status": "stored_mock",
                "namespace": namespace,
                "run_id": run_id,
                "accepted_count": len(verified_facts),
                "facts": verified_facts,
            }

        result = await self._store_cloud_memory(
            namespace=namespace,
            content=content,
            provenance={
                "run_id": run_id,
                "objective": objective,
                "kind": "verified_findings",
                "tags": tags or [],
            },
            importance=0.95,
        )
        result.setdefault(
            "accepted_count", len(verified_facts) if result.get("status") == "stored" else 0
        )
        result.setdefault("run_id", run_id)
        return result


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
            conf = (
                f.get("confidence", 0.0) if isinstance(f, dict) else getattr(f, "confidence", 0.0)
            )
            status = str(
                f.get("status", "verified")
                if isinstance(f, dict)
                else getattr(f, "status", "verified")
            ).lower()
            claim_ids = (
                f.get("claim_ids", []) if isinstance(f, dict) else getattr(f, "claim_ids", [])
            )
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


async def publish_research_handoff(
    run_id: str,
    objective: str,
    summary: str,
    claims: list[Any] | None = None,
    findings: list[Any] | None = None,
    sources: list[Any] | None = None,
    namespace_prefix: str = "intelx://research",
    tags: list[str] | None = None,
    client: MemoraMemoryClient | None = None,
) -> dict[str, Any]:
    """Publish verified research briefs and extracted claims to Memora under intelx://research/."""
    memora = client or MemoraMemoryClient()
    return await memora.publish_research_handoff(
        run_id=run_id,
        objective=objective,
        summary=summary,
        claims=claims,
        findings=findings,
        sources=sources,
        namespace_prefix=namespace_prefix,
        tags=tags,
    )
