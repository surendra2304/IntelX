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

    # 3. Query existing completed runs for findings matching the query (mesh dispatch path)
    # This mirrors the logic in /v1/task/execute which works reliably
    key_role = getattr(_api_key.role, "value", _api_key.role)
    run_stmt = select(ResearchRun.id).where(ResearchRun.status == RunStatus.COMPLETED)
    if str(key_role).lower() != "admin":
        run_stmt = run_stmt.where(ResearchRun.created_by == _api_key.name)

    query_terms = [word.strip(".,:;!?()[]{}\"'").lower() for word in query.split()]
    query_terms = [word for word in query_terms if len(word) >= 3][:6]
    if query_terms and query.lower() != "macro intelligence":
        run_stmt = run_stmt.where(
            or_(*(ResearchRun.objective.ilike(f"%{word}%") for word in query_terms))
        )
    run_stmt = run_stmt.order_by(ResearchRun.created_at.desc()).limit(20)
    run_ids = list((await session.execute(run_stmt)).scalars().all())

    if run_ids:
        claims_stmt = (
            select(Claim)
            .where(Claim.run_id.in_(run_ids), Claim.status != "DISPUTED")
            .order_by(Claim.created_at.desc())
            .limit(50)
        )
        claims = list((await session.execute(claims_stmt)).scalars().all())
        findings_stmt = (
            select(Finding)
            .where(Finding.run_id.in_(run_ids))
            .order_by(Finding.created_at.desc())
            .limit(5)
        )
        findings = list((await session.execute(findings_stmt)).scalars().all())
        needed_claim_ids = {
            str(claim_id) for finding in findings for claim_id in (finding.claim_ids_json or [])
        }
        known_claim_ids = {claim.id for claim in claims}
        missing_claim_ids = needed_claim_ids - known_claim_ids
        if missing_claim_ids:
            extra_stmt = select(Claim).where(
                Claim.id.in_(missing_claim_ids), Claim.run_id.in_(run_ids)
            )
            claims.extend((await session.execute(extra_stmt)).scalars().all())
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
    else:
        claims = []
        findings = []
        sources = []

    # Construct per-finding source citations from the exact supporting claims
    claims_by_id = {claim.id: claim for claim in claims}
    sources_by_id = {source.id: source for source in sources}
    findings_items = []
    for finding in findings:
        claim_ids = [str(claim_id) for claim_id in (finding.claim_ids_json or [])]
        citations = []
        for claim_id in claim_ids:
            claim = claims_by_id.get(claim_id)
            source = sources_by_id.get(claim.source_id) if claim else None
            if source:
                citations.append(
                    {
                        "source_id": source.id,
                        "source_title": source.title or "Source Document",
                        "source_url": source.location,
                    }
                )
        findings_items.append(
            {
                "finding_id": finding.id,
                "statement": finding.conclusion,
                "confidence_score": finding.confidence,
                "evidence_count": len(citations),
                "citations": citations,
                "status": "verified" if finding.confidence >= 0.70 else "inference",
                "claim_ids": claim_ids,
            }
        )

    if not findings_items and claims:
        for claim in claims[:5]:
            source = sources_by_id.get(claim.source_id)
            citations = (
                [
                    {
                        "source_id": source.id,
                        "source_title": source.title or "Source Document",
                        "source_url": source.location,
                    }
                ]
                if source
                else []
            )
            findings_items.append(
                {
                    "finding_id": f"cl-{claim.id[:8]}",
                    "statement": claim.text,
                    "confidence_score": claim.confidence,
                    "evidence_count": len(citations),
                    "citations": citations,
                    "status": "verified" if claim.confidence >= 0.75 else "inference",
                    "claim_ids": [claim.id],
                }
            )

    # Build provenance chain
    provenance_chain = []
    for cl in claims[:10]:
        matching_s = next((s for s in sources if s.id == cl.source_id), None)
        provenance_chain.append(
            {
                "claim_id": cl.id,
                "claim_text": cl.text,
                "quote": cl.quote,
                "span_start": cl.span_start,
                "span_end": cl.span_end,
                "document_id": cl.document_id,
                "source_id": cl.source_id,
                "source_title": matching_s.title if matching_s else "Source Document",
                "source_url": matching_s.location if matching_s else "internal://source",
                "publisher": matching_s.publisher if matching_s else None,
            }
        )

    sources_data = [
        {
            "id": s.id,
            "title": s.title,
            "url": s.location,
            "publisher": s.publisher,
            "trust_tier": str(s.trust_tier),
        }
        for s in sources[:5]
    ]

    # Generate spoken summary and text response using existing citation formatters
    spoken_summary = export_spoken_citations(findings_items, sources)
    text_response = export_text_citations(findings_items, sources)

    lat = int((time.time() - t0) * 1000)
    summary = f"IntelX synthesized evidence-driven research for query '{query}' with {len(sources_data)} cited sources."

    logger.info(
        f"[FRIDAY API] Mesh dispatch research query='{query[:60]}...' run_id={run_id} "
        f"findings={len(findings_items)} sources={len(sources_data)} latency_ms={lat}"
    )

    # Return the same response shape as the mesh dispatch: run_id, status, findings, citations, spoken_summary, sources
    return {
        "run_id": run_id,
        "status": "SUCCESS",
        "findings": findings_items,
        "citations": sources_data,  # sources_data serves as citations
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