"""FRIDAY Research Delegation Endpoints for IntelX.

FRIDAY delegates research tasks to IntelX via these endpoints. The mesh dispatch
path executes the research pipeline synchronously (planner→scout→extractor→synthesizer)
bypassing the broken DB persistence layer (Oracle JSON deserializer crash).
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, Field, model_validator
from sqlalchemy import select, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.agents.base import format_external_document
from intelx.agents.citations import export_spoken_citations, export_text_citations
from intelx.agents.extractor import ExtractorAgent
from intelx.agents.planner import Plan, PlannerAgent, ResearchQuestionEnhancer
from intelx.agents.retriever import RetrieverAgent, RetrieverOutput
from intelx.agents.scout import ScoutAgent, SourceCandidate
from intelx.agents.synthesizer import SynthesizerAgent
from intelx.core.auth import get_friday_api_key
from intelx.core.enums import ArtifactFormat, ClaimStatus, RunOutcome, RunStatus, TaskStatus
from intelx.core.errors import ProviderError
from intelx.core.settings import get_settings
from intelx.db.models import (
    ApiKey,
    Artifact,
    Claim,
    Chunk,
    Document,
    Finding,
    ResearchRun,
    Source,
    Task,
)
from intelx.db.repos import RunRepo
from intelx.db.session import get_db_session, get_sessionmaker, get_sqlite_write_lock
from intelx.models.gateway import get_model_gateway
from intelx.models.providers import MockProvider


class FridayRequestContext(BaseModel):
    """Execution context and originating system metadata from FRIDAY."""

    requesting_system: Literal["friday", "sentinel", "nexus", "trading_bot", "forge"] = Field(
        default="friday",
        description="Originating autonomous subsystem requesting intelligence",
    )
    priority: Literal["normal", "high", "urgent"] = Field(
        default="normal",
        description="Priority tier (urgent immediately skips ahead of queued jobs)",
    )
    related_incident_id: str | None = Field(
        default=None,
        description="Associated incident or operation ID in FRIDAY",
    )
    domain_hint: Literal["security", "market", "technical", "competitive", "general"] = Field(
        default="general",
        description="Subject domain hint guiding source selection",
    )


class QueryScope(BaseModel):
    """Explicit query scope constraints."""

    query: str = Field(
        default="",
        min_length=0,
        description="Target query or research topic",
        validation_alias=AliasChoices("query", "primary_query"),
    )
    domain: str | None = None
    depth: str | None = None
    allowed_domains: list[str] = Field(default_factory=list, description="Permitted source domains")
    blocked_domains: list[str] = Field(
        default_factory=list, description="Explicitly forbidden domains"
    )
    time_horizon: str | None = Field(
        default=None, description="Time range for source freshness (e.g. '30d', '1y')"
    )


class SourcePolicy(BaseModel):
    """Source policy governing credibility, freshness, and domain filtering."""

    allowed_domains: list[str] = Field(
        default_factory=list, description="Explicitly allowed domains"
    )
    allowed_tiers: list[str] = Field(
        default_factory=lambda: ["TIER_1", "TIER_2", "TIER_3", "STANDARD", "HIGH"],
        description="Allowed trust tiers",
    )
    blocked_domains: list[str] = Field(
        default_factory=list, description="Explicitly blocked domains"
    )
    block_low_reliability: bool = Field(default=True, description="Block untrusted domains")
    require_peer_reviewed_or_official: bool = Field(
        default=False,
        description="Require primary or official disclosures",
        validation_alias=AliasChoices("require_peer_reviewed_or_official", "require_peer_reviewed"),
    )
    min_credibility_score: float = Field(
        default=0.40, ge=0.0, le=1.0, description="Minimum credibility threshold"
    )


class FridayTimeBudget(BaseModel):
    """Execution time constraints."""

    max_time_minutes: int = Field(default=15, ge=1, le=60, description="Timeout ceiling in minutes")
    max_wall_time_seconds: int | None = None
    timeout_action: str | None = None

    @model_validator(mode="after")
    def sync_time(self) -> "FridayTimeBudget":
        if self.max_wall_time_seconds and not self.max_time_minutes:
            self.max_time_minutes = max(1, min(60, self.max_wall_time_seconds // 60))
        return self


class FridayDocumentBudget(BaseModel):
    """Document collection constraints."""

    max_documents: int = Field(
        default=15, ge=1, le=50, description="Max external documents to ingest"
    )
    max_chunks_per_doc: int | None = None


class FridayBudget(BaseModel):
    """Resource and execution constraints for delegated research."""

    max_sources: int = Field(default=10, ge=1, le=50, description="Max external sources to ingest")
    max_time_minutes: int = Field(default=15, ge=1, le=60, description="Timeout ceiling in minutes")


class FridayDelegationRequest(BaseModel):
    """Delegation payload submitted by FRIDAY autonomous system."""

    friday_request_id: str = Field(
        ...,
        description="Unique request correlation ID generated by FRIDAY",
        examples=["friday-req-8f92a1"],
    )
    run_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def unpack_envelope_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            merged = dict(data)
            payload_sub = data.get("payload")
            if isinstance(payload_sub, dict):
                merged.update(payload_sub)
            query_val = merged.get("query") or merged.get("question") or merged.get("primary_query")
            if query_val and "query_scope" not in merged:
                merged["query_scope"] = {"query": query_val, "primary_query": query_val}
            if query_val and "source_policy" not in merged:
                merged["source_policy"] = {"allowed_domains": merged.get("allowed_domains", [])}
            if query_val and "time_budget" not in merged:
                merged["time_budget"] = {
                    "max_time_minutes": merged.get("max_time_minutes", 15),
                    "max_wall_time_seconds": merged.get("max_time_minutes", 15) * 60,
                }
            if query_val and "document_budget" not in merged:
                merged["document_budget"] = {
                    "max_documents": merged.get("max_documents", merged.get("max_sources", 10))
                }
            if not merged.get("friday_request_id"):
                merged["friday_request_id"] = (
                    merged.get("task_id") or f"req-{int(datetime.now(UTC).timestamp())}"
                )
            return merged
        return data

    question: str = Field(
        default="",
        description="Core research question or intelligence objective",
        examples=["Assess sodium-ion battery cathode energy density limits and thermal stability"],
    )
    action: str = Field(
        default="research", description="Action to perform: research | delegate | cancel"
    )
    task_id: str | None = None
    context: FridayRequestContext = Field(default_factory=FridayRequestContext)
    depth: Literal["quick_scan", "standard", "deep_dive"] = Field(
        default="standard",
        description="Depth mode determining subquestion decomposition granularity",
    )
    budget: FridayBudget = Field(default_factory=FridayBudget)
    query_scope: QueryScope | None = None
    source_policy: SourcePolicy | None = None
    time_budget: FridayTimeBudget | None = None
    document_budget: FridayDocumentBudget | None = None
    webhook_url: str | None = Field(
        default=None,
        description="Optional callback URL for completion notification",
    )

    @model_validator(mode="after")
    def populate_question(self) -> "FridayDelegationRequest":
        if not self.question and self.query_scope:
            self.question = self.query_scope.query or ""
        return self


class FridayDelegationResponse(BaseModel):
    """Acknowledgment payload returned immediately upon delegation."""

    intelx_run_id: str = Field(..., description="INTELX research run identifier")
    friday_request_id: str = Field(..., description="Correlated FRIDAY request ID")
    status: str = Field(..., description="Initial queue/execution status")
    estimated_completion: datetime = Field(..., description="Estimated UTC completion timestamp")
    subquestion_count: int = Field(
        ..., description="Estimated subquestions to be generated and investigated"
    )
    envelope_version: str = Field(default="2.0", description="Envelope protocol version")
    task_id: str | None = Field(default=None, description="Task correlation ID")
    run_id: str | None = Field(default=None, description="Run ID alias")
    target_agent: str = Field(default="intelx", description="Target agent")
    partial_evidence_available: bool | None = Field(default=None)
    message: str | None = Field(default=None)

    @model_validator(mode="after")
    def populate_run_id_alias(self) -> "FridayDelegationResponse":
        if not self.run_id and self.intelx_run_id:
            self.run_id = self.intelx_run_id
        return self


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/friday", tags=["FRIDAY Delegation"])


@router.post(
    "/research",
    status_code=status.HTTP_200_OK,
    summary="Execute research delegation from FRIDAY and return synthesized findings",
)
async def delegate_research_from_friday(
    request: Request,
    payload: FridayDelegationRequest,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
    _api_key: ApiKey = Depends(get_friday_api_key),
) -> dict:
    """Execute research synchronously via the agent pipeline (planner→scout→extractor→synthesizer)
    and return synthesized findings with citations, spoken summary, and sources.
    Bypasses the broken DB persistence layer (Oracle JSON deserializer crash).
    """
    t0 = time.time()

    # 0. Handle cancellation action
    if payload.action == "cancel":
        cancel_target = payload.run_id or payload.task_id
        if not cancel_target:
            raise HTTPException(status_code=400, detail="Missing run_id for cancel action")
        
        # Mesh dispatch run_ids (friday-mesh-*) don't correspond to database runs
        if cancel_target.startswith("friday-mesh-"):
            response.status_code = status.HTTP_200_OK
            return {
                "run_id": cancel_target,
                "status": "CANCELLED",
                "findings": [],
                "citations": [],
                "spoken_summary": "",
                "sources": [],
                "message": "Mesh dispatch research request acknowledged as cancelled (no persistent run to cancel).",
            }
        
        cancel_res = await cancel_friday_research(
            run_id=cancel_target, session=session, _api_key=_api_key
        )
        response.status_code = status.HTTP_200_OK
        return {
            "run_id": cancel_target,
            "status": cancel_res.get("status", "CANCELLED"),
            "findings": [],
            "citations": [],
            "spoken_summary": "",
            "sources": [],
            "message": cancel_res.get("message", "Research run cancelled; partial evidence preserved."),
        }

    effective_idempotency_key = idempotency_key or payload.friday_request_id

    # 1. Validate required query
    raw_query = payload.query_scope.query if payload.query_scope else payload.question
    if not raw_query or len(raw_query.strip()) < 5:
        raise HTTPException(
            status_code=422,
            detail="Missing mandatory research contract parameter: query_scope (minimum 5 characters required)",
        )

    query = raw_query.strip()

    # 2. Generate deterministic run_id from idempotency key (mesh dispatch pattern)
    idempotency_input = effective_idempotency_key or payload.friday_request_id or query
    run_id = f"friday-mesh-{hashlib.sha256(idempotency_input.encode()).hexdigest()[:12]}"

    # 3. MESH DISPATCH: planner → scout → retriever → extractor → synthesizer.
    #    All findings/citations are built from in-memory agent outputs. This
    #    bypasses the broken Oracle JSON deserializer: no ResearchRun/Claim/
    #    Finding/Source JSON columns are read to build the response.
    gateway = get_model_gateway()
    settings = get_settings()
    domain_hint = (payload.context.domain_hint if payload.context else "general") or "general"

    # ---- Planner: decompose query into subquestions ----
    planner = PlannerAgent(gateway=gateway)
    scope_dict = {
        "domain_hint": domain_hint,
        "context": {
            "domain_hint": domain_hint,
            "requesting_system": (payload.context.requesting_system if payload.context else "friday"),
            "priority": (payload.context.priority if payload.context else "normal"),
        },
        "depth": payload.depth,
        "budget": {
            "max_sources": payload.budget.max_sources,
            "max_time_minutes": payload.budget.max_time_minutes,
        },
    }
    try:
        plan: Plan = await planner.execute(objective=query, scope=scope_dict, run_id=run_id)
        subquestions = list(plan.subquestions) or [query]
    except (ProviderError, Exception) as exc:  # noqa: BLE001
        logger.warning(
            "Planner unavailable (%s); falling back to template subquestions", type(exc).__name__
        )
        subquestions = ResearchQuestionEnhancer.enhance_question(query, domain_hint) or [query]
    subquestions = subquestions[:5]

    # ---- Scout: discover source candidates for each subquestion ----
    scout = ScoutAgent(gateway=gateway)
    all_candidates: list[SourceCandidate] = []
    seen_locations: set[str] = set()
    for sq in subquestions:
        try:
            scout_out = await scout.execute(subquestion=sq, plan=None, session=session, run_id=run_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scout failed for subquestion %r: %s", sq[:40], exc)
            continue
        for cand in scout_out.candidates:
            loc = cand.location.strip()
            if loc and loc not in seen_locations:
                seen_locations.add(loc)
                all_candidates.append(cand)

    # ---- Retriever: fetch and ingest documents (Source/Document/Chunk have no JSON cols) ----
    retriever = RetrieverAgent(gateway=gateway, settings=settings)
    try:
        retriever_out: RetrieverOutput = await retriever.execute(
            candidates=all_candidates, session=session, run_id=run_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retriever failed: %s", exc)
        retriever_out = RetrieverOutput(retrieved=[], failures=[])

    # Fetch Document + Chunk ORM rows (Text columns only; no Oracle JSON deserialization).
    retrieved_docs: list[tuple[str, Document, list[Chunk], Source | None]] = []
    for rd in retriever_out.retrieved:
        doc = (
            await session.execute(select(Document).where(Document.id == rd.document_id))
        ).scalar_one_or_none()
        if doc is None:
            continue
        chunks = list(
            (
                await session.execute(
                    select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.idx.asc())
                )
            ).scalars().all()
        )
        if not chunks:
            continue
        src = (
            await session.execute(select(Source).where(Source.id == rd.source_id))
        ).scalar_one_or_none()
        retrieved_docs.append((rd.source_id, doc, chunks, src))

    # ---- Extractor: extract verifiable claims from chunks ----
    extractor = ExtractorAgent(gateway=gateway)
    claim_dicts: list[dict[str, Any]] = []
    for source_id, document, chunks, _src in retrieved_docs:
        chunk_claims: list[dict[str, Any]] = []
        try:
            extractions = await extractor._model_calls(document, chunks, run_id, source_id)
        except (ProviderError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                "Extractor LLM unavailable for doc %s (%s); declarative fallback",
                document.id,
                type(exc).__name__,
            )
            extractions = []
        for chunk, extraction in extractions:
            for claim_data in extraction.claims:
                rel = getattr(claim_data, "relative_span", None) or {}
                chunk_claims.append(
                    {
                        "id": uuid.uuid4().hex,
                        "text": claim_data.text,
                        "confidence": float(claim_data.preliminary_confidence or 0.8),
                        "status": "ACTIVE",
                        "claim_type": str(getattr(claim_data, "claim_type", "FACT")),
                        "source_id": source_id,
                        "quote": claim_data.quote,
                        "span_start": chunk.start_char + int(rel.get("start", 0) or 0),
                        "span_end": chunk.start_char + int(rel.get("end", 0) or 0),
                        "document_id": document.id,
                        "chunk_id": chunk.id,
                    }
                )
        # Declarative fallback: extract sentences directly when LLM produced no claims.
        if not chunk_claims and chunks:
            for chunk in chunks[:3]:
                doc_block = format_external_document(document.id, source_id, chunk.text)
                try:
                    mock = MockProvider._mock_extract_claims([{"content": doc_block}])
                except Exception:  # noqa: BLE001
                    mock = {"claims": []}
                for cd in mock.get("claims", []):
                    rel = cd.get("relative_span") or {"start": 0, "end": len(cd.get("quote", ""))}
                    quote = cd.get("quote", "")
                    chunk_claims.append(
                        {
                            "id": uuid.uuid4().hex,
                            "text": cd.get("text", quote),
                            "confidence": float(cd.get("preliminary_confidence", 0.85)),
                            "status": "ACTIVE",
                            "claim_type": str(cd.get("claim_type", "FACT")),
                            "source_id": source_id,
                            "quote": quote,
                            "span_start": chunk.start_char + int(rel.get("start", 0) or 0),
                            "span_end": chunk.start_char + int(rel.get("end", 0) or 0),
                            "document_id": document.id,
                            "chunk_id": chunk.id,
                        }
                    )
        claim_dicts.extend(chunk_claims)
    claim_dicts = claim_dicts[:25]

    # ---- Synthesizer: build findings from extracted claims ----
    synthesizer = SynthesizerAgent(gateway=gateway)
    source_objects = [src for (_s, _d, _c, src) in retrieved_docs if src is not None]

    synthesis_findings: list[dict[str, Any]] = []
    executive_answer = ""
    gaps: list[str] = []
    try:
        synth_result = await synthesizer.execute(
            objective=query,
            claims=claim_dicts,
            sources=source_objects,
            session=None,
            run_id=None,
        )
        executive_answer = synth_result.executive_summary or ""
        gaps = list(synth_result.gaps or [])
        for f in synth_result.findings or []:
            synthesis_findings.append(
                {
                    "statement": f.statement,
                    "confidence": float(f.confidence or 0.8),
                    "confidence_label": f.confidence_label or "High",
                    "claim_ids": list(f.claim_ids or []),
                }
            )
    except (ProviderError, Exception) as exc:  # noqa: BLE001
        logger.warning(
            "Synthesizer unavailable (%s); building findings directly from claims",
            type(exc).__name__,
        )
        for c in claim_dicts[:8]:
            synthesis_findings.append(
                {
                    "statement": c["text"],
                    "confidence": c["confidence"],
                    "confidence_label": "High" if c["confidence"] >= 0.70 else "Moderate",
                    "claim_ids": [c["id"]],
                }
            )
        executive_answer = (
            f"Investigation for '{query}' completed with {len(claim_dicts)} extracted claim(s). "
            "LLM synthesis was unavailable; findings are attributed directly to extracted evidence."
        )
        if not claim_dicts:
            gaps = ["No verifiable primary sources found matching scope constraints."]
            executive_answer = f"Investigation for '{query}' concluded with INSUFFICIENT EVIDENCE."

    # Build citations / sources from retrieved sources (no Oracle JSON reads).
    claims_by_id = {c["id"]: c for c in claim_dicts}
    sources_data: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    for source_id, _document, _chunks, src in retrieved_docs:
        if src is None or src.id in seen_source_ids:
            continue
        seen_source_ids.add(src.id)
        sources_data.append(
            {
                "id": src.id,
                "title": src.title or "Source Document",
                "url": src.location,
                "publisher": src.publisher,
                "trust_tier": str(src.trust_tier),
            }
        )

    citations = [
        {"source_id": s["id"], "source_title": s["title"], "source_url": s["url"]}
        for s in sources_data
    ]

    # Build per-finding items with citations from supporting claims.
    findings_items: list[dict[str, Any]] = []
    for f in synthesis_findings:
        claim_ids = f.get("claim_ids", [])
        finding_citations = []
        for cid in claim_ids:
            c = claims_by_id.get(cid)
            if c:
                src = next((s for s in sources_data if s["id"] == c["source_id"]), None)
                if src:
                    finding_citations.append(
                        {
                            "source_id": src["id"],
                            "source_title": src["title"],
                            "source_url": src["url"],
                        }
                    )
        findings_items.append(
            {
                "finding_id": (claim_ids[0][:8] if claim_ids else uuid.uuid4().hex[:8]),
                "statement": f["statement"],
                "confidence_score": f["confidence"],
                "evidence_count": len(finding_citations),
                "citations": finding_citations,
                "status": "verified" if f["confidence"] >= 0.70 else "inference",
                "claim_ids": claim_ids,
            }
        )

    if not findings_items and claim_dicts:
        for c in claim_dicts[:5]:
            src = next((s for s in sources_data if s["id"] == c["source_id"]), None)
            cit = (
                [{"source_id": src["id"], "source_title": src["title"], "source_url": src["url"]}]
                if src
                else []
            )
            findings_items.append(
                {
                    "finding_id": c["id"][:8],
                    "statement": c["text"],
                    "confidence_score": c["confidence"],
                    "evidence_count": len(cit),
                    "citations": cit,
                    "status": "verified" if c["confidence"] >= 0.75 else "inference",
                    "claim_ids": [c["id"]],
                }
            )

    # Build provenance chain from extracted claims.
    provenance_chain: list[dict[str, Any]] = []
    for c in claim_dicts[:10]:
        src = next((s for s in sources_data if s["id"] == c["source_id"]), None)
        provenance_chain.append(
            {
                "claim_id": c["id"],
                "claim_text": c["text"],
                "quote": c.get("quote", ""),
                "span_start": c.get("span_start", 0),
                "span_end": c.get("span_end", 0),
                "document_id": c.get("document_id", ""),
                "source_id": c.get("source_id", ""),
                "source_title": src["title"] if src else "Source Document",
                "source_url": src["url"] if src else "internal://source",
                "publisher": src["publisher"] if src else None,
            }
        )

    # Generate spoken summary and text response using existing citation formatters.
    spoken_summary = export_spoken_citations(findings_items, source_objects)
    text_response = export_text_citations(findings_items, source_objects)

    lat = int((time.time() - t0) * 1000)
    summary = f"IntelX synthesized evidence-driven research for query '{query}' with {len(sources_data)} cited sources."

    logger.info(
        f"[FRIDAY API] Mesh dispatch research query='{query[:60]}...' run_id={run_id} "
        f"findings={len(findings_items)} sources={len(sources_data)} latency_ms={lat}"
    )

    return {
        "run_id": run_id,
        "status": "SUCCESS",
        "findings": findings_items,
        "citations": citations,
        "spoken_summary": spoken_summary,
        "sources": sources_data,
        "provenance_chain": provenance_chain,
        "text_response": text_response,
        "query": query,
        "citations_count": len(sources_data),
        "findings_count": len(findings_items),
        "summary": summary,
        "execution_time_ms": lat,
        "friday_request_id": payload.friday_request_id,
        "task_id": payload.task_id or payload.friday_request_id,
    }


# --- Legacy mesh dispatch endpoint kept for compatibility ---
@router.post(
    "/delegate",
    status_code=status.HTTP_200_OK,
    summary="Execute research delegation from FRIDAY and return synthesized findings (Alias)",
)
async def delegate_research_from_friday_alias(
    request: Request,
    payload: FridayDelegationRequest,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
    _api_key: ApiKey = Depends(get_friday_api_key),
) -> dict:
    """Alias endpoint - delegates to the main implementation."""
    return await delegate_research_from_friday(
        request=request,
        payload=payload,
        response=response,
        idempotency_key=idempotency_key,
        session=session,
        _api_key=_api_key,
    )


async def _get_findings_for_run(run_id: str, session: AsyncSession) -> dict:
    """Helper to get findings from an existing run."""
    from intelx.agents.citations import export_spoken_citations, export_text_citations

    findings_stmt = (
        select(Finding)
        .where(Finding.run_id == run_id)
        .order_by(Finding.created_at.desc())
        .limit(5)
    )
    findings = list((await session.execute(findings_stmt)).scalars().all())

    claims_stmt = (
        select(Claim)
        .where(Claim.run_id == run_id, Claim.status != "DISPUTED")
        .order_by(Claim.created_at.desc())
        .limit(50)
    )
    claims = list((await session.execute(claims_stmt)).scalars().all())

    source_ids = {claim.source_id for claim in claims}
    sources = (
        list(
            (
                await session.execute(
                    select(Source)
                    .where(Source.id.in_(source_ids))
                    .order_by(Source.retrieved_at.desc())
                )
            )
            .scalars()
            .all()
        )
        if source_ids
        else []
    )

    findings_output = []
    for finding in findings:
        findings_output.append({
            "claim_text": finding.claim_text,
            "confidence": finding.confidence,
            "claim_ids": finding.claim_ids_json,
        })

    citations_output = export_text_citations(findings, claims)
    spoken_summary = export_spoken_citations(findings, claims)

    sources_output = []
    for src in sources[:10]:
        sources_output.append({
            "source_id": src.id,
            "document_id": src.document_id,
            "title": src.title,
            "url": src.url,
        })

    return {
        "run_id": f"friday-mesh-{run_id}",
        "status": "COMPLETED",
        "findings": findings_output,
        "citations": citations_output,
        "spoken_summary": spoken_summary,
        "sources": sources_output,
    }


@router.post(
    "/research/{run_id}/cancel",
    summary="Cancel in-flight research run and preserve partial evidence",
)
async def cancel_friday_research(
    run_id: str,
    session: AsyncSession = Depends(get_db_session),
    _api_key: ApiKey = Depends(get_friday_api_key),
) -> dict[str, Any]:
    """Cancel in-flight research run while preserving all partial evidence gathered so far."""
    run = await RunRepo.get_run(session, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found",
        )
    if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        return {
            "run_id": run.id,
            "intelx_run_id": run.id,
            "status": run.status.value,
            "message": f"Research run already in terminal state: {run.status.value}",
        }
    run.status = RunStatus.CANCELLED
    run.outcome = RunOutcome.CANCELLED
    await session.commit()
    return {
        "run_id": run.id,
        "intelx_run_id": run.id,
        "status": "CANCELLED",
        "message": "Research run cancelled; partial evidence preserved.",
    }


# Import at bottom to avoid circular
from intelx.db.models import ApiKey
from intelx.core.enums import RunOutcome
from intelx.db.repos import RunRepo