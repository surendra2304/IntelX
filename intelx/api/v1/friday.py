"""FRIDAY Autonomous System Delegation and Intelligence Consumer API Endpoints."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.agents.citations import export_spoken_citations, export_text_citations
from intelx.core.auth import get_friday_api_key
from intelx.core.enums import ArtifactFormat, ClaimStatus, RunOutcome, RunStatus, TaskStatus
from intelx.db.models import (
    ApiKey,
    Artifact,
    Claim,
    Document,
    Evidence,
    Finding,
    ResearchRun,
    Source,
    Task,
)
from intelx.db.repos import RunRepo
from intelx.db.session import get_db_session, get_sessionmaker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/friday", tags=["FRIDAY Delegation"])


# ============================================================================
# Request / Response Schemas
# ============================================================================


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
    blocked_domains: list[str] = Field(default_factory=list, description="Explicitly forbidden domains")
    time_horizon: str | None = Field(default=None, description="Time range for source freshness (e.g. '30d', '1y')")


class SourcePolicy(BaseModel):
    """Source policy governing credibility, freshness, and domain filtering."""

    allowed_domains: list[str] = Field(default_factory=list, description="Explicitly allowed domains")
    allowed_tiers: list[str] = Field(
        default_factory=lambda: ["TIER_1", "TIER_2", "TIER_3", "STANDARD", "HIGH"],
        description="Allowed trust tiers",
    )
    blocked_domains: list[str] = Field(default_factory=list, description="Explicitly blocked domains")
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

    max_documents: int = Field(default=15, ge=1, le=50, description="Max external documents to ingest")
    max_chunks_per_doc: int | None = None


class FridayProvenanceItem(BaseModel):
    """Granular provenance chain link from finding to external source."""

    finding_id: str
    finding_conclusion: str
    claim_id: str
    claim_text: str
    evidence_id: str | None = None
    quote: str
    span_start: int
    span_end: int
    document_id: str
    source_id: str
    source_url: str
    source_title: str
    publisher: str | None = None
    retrieved_at: str | None = None


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
    question: str = Field(
        default="",
        description="Core research question or intelligence objective",
        examples=["Assess sodium-ion battery cathode energy density limits and thermal stability"],
    )
    action: str = Field(default="research", description="Action to perform: research | delegate | cancel")
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


class TaskEnvelope(BaseModel):
    """Standard FRIDAY Universe Task Envelope."""

    task_id: str = Field(..., description="Unique task identifier")
    source_agent: str = Field(default="friday", description="Source subsystem")
    target_agent: str = Field(default="intelx", description="Target specialist agent")
    action: str = Field(default="research", description="Action: research | query | cancel")
    payload: dict[str, Any] = Field(default_factory=dict, description="Task parameters")
    priority: Literal["normal", "high", "urgent"] = Field(default="normal")
    idempotency_key: str | None = Field(default=None)


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


class FridayProgress(BaseModel):
    """Execution progress metrics for a research run."""

    subquestions_completed: int = Field(default=0)
    subquestions_total: int = Field(default=1)
    percent: float = Field(default=0.0)


class FridayRunStatusResponse(BaseModel):
    """Run lifecycle, phase, and live entity counts for FRIDAY."""

    run_id: str
    friday_request_id: str | None
    status: str
    current_phase: Literal[
        "queued",
        "planning",
        "retrieval",
        "extraction",
        "verification",
        "analysis",
        "synthesis",
        "completed",
        "failed",
        "cancelled",
    ]
    progress: FridayProgress
    findings_count: int
    claims_count: int
    contradiction_count: int
    usd_cost: float
    duration_seconds: float | None
    is_partial: bool = False
    outcome: str | None = None


class FridayCitation(BaseModel):
    """Evidence citation grounding a finding."""

    source_title: str
    source_url: str
    verbatim_span: str


class FridayFindingItem(BaseModel):
    """Structured research finding with confidence and citations."""

    finding_id: str
    statement: str
    confidence_score: float
    evidence_count: int
    citations: list[FridayCitation] = Field(default_factory=list)
    status: Literal["verified", "disputed", "unverified", "inference"]
    is_inference: bool = False
    provenance: list[FridayProvenanceItem] = Field(default_factory=list)


class FridayFindingsResponse(BaseModel):
    """Collection of structured research findings for FRIDAY."""

    run_id: str
    findings: list[FridayFindingItem] = Field(default_factory=list)


class FridayReportResponse(BaseModel):
    """Full intelligence report with resolved citations in Markdown and JSON."""

    run_id: str
    objective: str
    report_markdown: str
    report_json: dict[str, Any]
    citations_resolved: bool
    spoken_summary: str = ""
    text_response: str = ""
    provenance_chain: list[FridayProvenanceItem] = Field(default_factory=list)


class FridayClaimRef(BaseModel):
    """Claim representation in contradiction pair."""

    claim_id: str
    text: str
    quote: str
    source_id: str
    source_title: str
    source_url: str


class FridayContradiction(BaseModel):
    """Opposing claims with conflicting evidence for FRIDAY review."""

    contradiction_id: str
    topic_or_subject: str
    claim_a: FridayClaimRef
    claim_b: FridayClaimRef
    divergence_description: str


class FridayContradictionsResponse(BaseModel):
    """Collection of disputed claims with opposing evidence."""

    run_id: str
    contradiction_count: int
    contradictions: list[FridayContradiction] = Field(default_factory=list)


# ============================================================================
# Helpers
# ============================================================================


def map_run_phase(run_status: RunStatus) -> str:
    """Map internal RunStatus to standard FRIDAY phase."""
    mapping = {
        RunStatus.QUEUED: "queued",
        RunStatus.PLANNING: "planning",
        RunStatus.DISCOVERING: "retrieval",
        RunStatus.RETRIEVING: "retrieval",
        RunStatus.EXTRACTING: "extraction",
        RunStatus.VERIFYING: "verification",
        RunStatus.ANALYZING: "analysis",
        RunStatus.SYNTHESIZING: "synthesis",
        RunStatus.REVIEW_REQUIRED: "synthesis",
        RunStatus.COMPLETED: "completed",
        RunStatus.FAILED: "failed",
        RunStatus.CANCELLED: "cancelled",
    }
    return mapping.get(run_status, "queued")


# ============================================================================
# Endpoints
# ============================================================================


@router.post(
    "/research",
    response_model=FridayDelegationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Accept research delegation from FRIDAY",
)
@router.post(
    "/delegate",
    response_model=FridayDelegationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Accept research delegation from FRIDAY (Alias)",
)
async def delegate_research_from_friday(
    request: Request,
    payload: FridayDelegationRequest,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
    _api_key: ApiKey = Depends(get_friday_api_key),
) -> FridayDelegationResponse:
    """Submit a research delegation job from FRIDAY with priority queue handling and contract validation."""
    effective_idempotency_key = idempotency_key or payload.friday_request_id

    # 1. Idempotency Check: Return existing run if already present
    if effective_idempotency_key:
        stmt_existing = select(ResearchRun).where(ResearchRun.idempotency_key == effective_idempotency_key)
        existing_run = (await session.execute(stmt_existing)).scalar_one_or_none()
        if existing_run:
            logger.info(
                f"[FRIDAY API] Idempotency hit: run={existing_run.id} for key={effective_idempotency_key}"
            )
            response.status_code = status.HTTP_200_OK
            depth = (
                existing_run.scope_json.get("depth", "standard")
                if isinstance(existing_run.scope_json, dict)
                else "standard"
            )
            subq_est = 2 if depth == "quick_scan" else (4 if depth == "standard" else 6)
            return FridayDelegationResponse(
                intelx_run_id=existing_run.id,
                friday_request_id=payload.friday_request_id,
                status=existing_run.status.value,
                estimated_completion=existing_run.completed_at
                or (datetime.now(UTC) + timedelta(minutes=5)),
                subquestion_count=subq_est,
                task_id=payload.task_id,
            )

    # 2. Mandatory Contract Validation (Query Scope, Source Policy, Time Budget, Document Budget)
    is_delegate_endpoint = request.url.path.endswith("/delegate") or payload.action == "delegate"
    if is_delegate_endpoint:
        missing_dims = []
        if not payload.query_scope:
            missing_dims.append("query_scope")
        if not payload.source_policy:
            missing_dims.append("source_policy")
        if not payload.time_budget:
            missing_dims.append("time_budget")
        if not payload.document_budget:
            missing_dims.append("document_budget")
        if missing_dims:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Missing mandatory FRIDAY research contract dimensions: {', '.join(missing_dims)}",
            )

    raw_query = payload.query_scope.query if payload.query_scope else payload.question
    if not raw_query or len(raw_query.strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing mandatory research contract parameter: query_scope (minimum 5 characters required)",
        )

    time_minutes = (
        payload.time_budget.max_time_minutes
        if payload.time_budget
        else payload.budget.max_time_minutes
    )
    if time_minutes < 1 or time_minutes > 60:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid mandatory research contract parameter: time_budget (must be between 1 and 60 minutes)",
        )

    doc_count = (
        payload.document_budget.max_documents
        if payload.document_budget
        else payload.budget.max_sources
    )
    if doc_count < 1 or doc_count > 50:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid mandatory research contract parameter: document_budget (must be between 1 and 50 documents)",
        )

    query_scope_obj = payload.query_scope or QueryScope(query=payload.question)
    source_policy_obj = payload.source_policy or SourcePolicy()
    time_budget_obj = payload.time_budget or FridayTimeBudget(max_time_minutes=time_minutes)
    document_budget_obj = payload.document_budget or FridayDocumentBudget(max_documents=doc_count)

    subquestion_estimate = (
        2 if payload.depth == "quick_scan" else (4 if payload.depth == "standard" else 6)
    )
    est_duration_minutes = min(
        time_minutes,
        3 if payload.depth == "quick_scan" else (10 if payload.depth == "standard" else 20),
    )
    est_completion = datetime.now(UTC) + timedelta(minutes=est_duration_minutes)

    scope_data = {
        "depth": payload.depth,
        "query_scope": query_scope_obj.model_dump(),
        "source_policy": source_policy_obj.model_dump(),
        "time_budget": time_budget_obj.model_dump(),
        "document_budget": document_budget_obj.model_dump(),
        "max_sources": doc_count,
        "budget": {
            "max_usd": 2.50 if payload.depth == "deep_dive" else 1.50,
            "max_minutes": time_minutes,
        },
        "friday_request_id": payload.friday_request_id,
        "idempotency_key": effective_idempotency_key,
        "context": payload.context.model_dump(),
        "priority": payload.context.priority,
        "webhook_url": payload.webhook_url,
    }

    run = await RunRepo.create_run(
        session=session,
        objective=payload.question,
        scope_json=scope_data,
        created_by=f"friday:{payload.context.requesting_system}",
    )
    run.idempotency_key = effective_idempotency_key
    await session.commit()

    logger.info(
        f"[FRIDAY API] Enqueued research delegation run={run.id} "
        f"friday_req={payload.friday_request_id} priority={payload.context.priority}"
    )

    return FridayDelegationResponse(
        intelx_run_id=run.id,
        friday_request_id=payload.friday_request_id,
        status=run.status.value,
        estimated_completion=est_completion,
        subquestion_count=subquestion_estimate,
    )


@router.post(
    "/delegate",
    summary="Execute research delegation using FRIDAY TaskEnvelope or DelegationRequest",
)
async def delegate_from_friday_envelope(
    envelope: dict[str, Any],
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
    _api_key: ApiKey = Depends(get_friday_api_key),
) -> dict[str, Any]:
    """Universal FRIDAY Task Envelope delegation gateway."""
    action = str(envelope.get("action", "research")).lower().strip()
    if action == "cancel":
        run_id = (
            envelope.get("payload", {}).get("run_id")
            or envelope.get("run_id")
            or envelope.get("task_id")
        )
        if not run_id:
            raise HTTPException(status_code=400, detail="Missing run_id for cancel action")
        return await cancel_friday_research(run_id=run_id, session=session, _api_key=_api_key)

    payload_data = (
        envelope.get("payload") if isinstance(envelope.get("payload"), dict) else envelope
    )
    req_id = (
        envelope.get("task_id")
        or payload_data.get("friday_request_id")
        or f"friday-{int(datetime.now(UTC).timestamp())}"
    )
    question = (
        payload_data.get("question")
        or payload_data.get("query")
        or payload_data.get("objective")
        or payload_data.get("prompt")
        or payload_data.get("topic")
    )
    if not question or len(str(question).strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing mandatory research contract parameter: query_scope (minimum 5 characters required)",
        )

    delegation_payload = FridayDelegationRequest(
        friday_request_id=req_id,
        question=str(question).strip(),
        context=FridayRequestContext(
            requesting_system=envelope.get("source_agent", "friday")
            if envelope.get("source_agent") in ("friday", "sentinel", "nexus", "trading_bot", "forge")
            else "friday",
            priority=envelope.get("priority", "normal")
            if envelope.get("priority") in ("normal", "high", "urgent")
            else "normal",
            domain_hint=payload_data.get("domain_hint", "general")
            if payload_data.get("domain_hint") in ("security", "market", "technical", "competitive", "general")
            else "general",
        ),
        depth=payload_data.get("depth", "standard")
        if payload_data.get("depth") in ("quick_scan", "standard", "deep_dive")
        else "standard",
        budget=FridayBudget(
            max_sources=payload_data.get("max_sources", payload_data.get("max_documents", 10)),
            max_time_minutes=payload_data.get("max_time_minutes", 15),
        ),
        query_scope=QueryScope(query=str(question).strip())
        if "query_scope" not in payload_data
        else payload_data["query_scope"],
        source_policy=SourcePolicy()
        if "source_policy" not in payload_data
        else payload_data["source_policy"],
        time_budget=FridayTimeBudget(max_time_minutes=payload_data.get("max_time_minutes", 15)),
        document_budget=FridayDocumentBudget(max_documents=payload_data.get("max_documents", 15)),
    )

    del_resp = await delegate_research_from_friday(
        payload=delegation_payload,
        response=response,
        idempotency_key=idempotency_key or envelope.get("idempotency_key"),
        session=session,
        _api_key=_api_key,
    )

    return {
        "task_id": envelope.get("task_id", req_id),
        "target_agent": "intelx",
        "status": "ACCEPTED" if del_resp.status == "QUEUED" else del_resp.status,
        "run_id": del_resp.intelx_run_id,
        "friday_request_id": del_resp.friday_request_id,
        "estimated_completion": del_resp.estimated_completion.isoformat(),
        "subquestion_count": del_resp.subquestion_count,
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
            "message": f"Run is already in terminal state '{run.status.value}'",
            "partial_evidence_available": True,
        }

    run.status = RunStatus.CANCELLED
    run.outcome = RunOutcome.CANCELLED
    run.completed_at = datetime.now(UTC)
    if run.error_json is None:
        run.error_json = {}
    run.error_json["cancel_requested"] = True

    await RunRepo.add_event(
        session=session,
        run_id=run_id,
        event_type="run.cancelled",
        payload_json={"reason": "Cancelled by FRIDAY request"},
    )
    await session.commit()
    logger.info(f"[FRIDAY API] Run {run_id} cancelled; partial evidence preserved.")
    return {
        "run_id": run.id,
        "intelx_run_id": run.id,
        "status": "cancelled",
        "message": "Research run cancelled; partial evidence preserved.",
        "partial_evidence_available": True,
    }


@router.get(
    "/research/{run_id}",
    response_model=FridayRunStatusResponse,
    summary="Get status, phase, and progress of delegated research run",
)
async def get_friday_research_status(
    run_id: str,
    session: AsyncSession = Depends(get_db_session),
    _api_key: ApiKey = Depends(get_friday_api_key),
) -> FridayRunStatusResponse:
    """Retrieve run status, current phase, progress, and finding/claim counters."""
    run = await RunRepo.get_run(session, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found",
        )

    # Subquestions and tasks progress
    stmt_tasks = select(Task).where(Task.run_id == run_id)
    tasks = list((await session.execute(stmt_tasks)).scalars().all())
    total_tasks = max(len(tasks), 1)
    completed_tasks = len(
        [t for t in tasks if t.status in (TaskStatus.SUCCEEDED, "SUCCEEDED", "COMPLETED")]
    )

    subquestions_total = 1
    if run.plan_json and "subquestions" in run.plan_json:
        subquestions_total = max(len(run.plan_json["subquestions"]), 1)
    elif run.scope_json.get("depth") == "quick_scan":
        subquestions_total = 2
    elif run.scope_json.get("depth") == "deep_dive":
        subquestions_total = 6
    else:
        subquestions_total = 4

    subquestions_completed = 0
    if run.status == RunStatus.COMPLETED:
        subquestions_completed = subquestions_total
        pct = 100.0
    elif run.status in (RunStatus.QUEUED, RunStatus.PLANNING):
        subquestions_completed = 0
        pct = 10.0 if run.status == RunStatus.PLANNING else 0.0
    else:
        fraction = completed_tasks / total_tasks if total_tasks > 0 else 0.5
        subquestions_completed = min(int(fraction * subquestions_total), subquestions_total - 1)
        pct = round(fraction * 90.0, 1)

    # Entity counts
    stmt_claims = select(Claim).where(Claim.run_id == run_id)
    claims = list((await session.execute(stmt_claims)).scalars().all())
    claims_count = len(claims)
    contradiction_count = len([c for c in claims if c.status == ClaimStatus.DISPUTED])

    stmt_findings = select(Finding).where(Finding.run_id == run_id)
    findings = list((await session.execute(stmt_findings)).scalars().all())
    findings_count = len(findings)

    duration = None
    if run.started_at:
        end_t = run.completed_at or datetime.now(UTC)
        duration = round((end_t - run.started_at).total_seconds(), 2)

    friday_req_id = (
        run.scope_json.get("friday_request_id") if isinstance(run.scope_json, dict) else None
    )

    is_partial = (
        run.status in (RunStatus.CANCELLED, "CANCELLED", RunStatus.FAILED, "FAILED")
        and (claims_count > 0 or findings_count > 0)
    ) or run.status in (RunStatus.CANCELLED, "CANCELLED")
    outcome_str = run.outcome.value if run.outcome else None

    return FridayRunStatusResponse(
        run_id=run.id,
        friday_request_id=friday_req_id,
        status=run.status.value,
        current_phase=map_run_phase(run.status),
        progress=FridayProgress(
            subquestions_completed=subquestions_completed,
            subquestions_total=subquestions_total,
            percent=pct,
        ),
        findings_count=findings_count,
        claims_count=claims_count,
        contradiction_count=contradiction_count,
        usd_cost=round(run.usd_cost, 6),
        duration_seconds=duration,
        is_partial=is_partial,
        outcome=outcome_str,
    )


@router.get(
    "/research/{run_id}/findings",
    response_model=FridayFindingsResponse,
    summary="Get structured findings with citations and confidence scores",
)
async def get_friday_research_findings(
    run_id: str,
    session: AsyncSession = Depends(get_db_session),
    _api_key: ApiKey = Depends(get_friday_api_key),
) -> FridayFindingsResponse:
    """Return all synthesized findings grounded in citations for FRIDAY."""
    run = await RunRepo.get_run(session, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found",
        )

    # Load all sources and claims for citation resolution
    sources_stmt = select(Source)
    sources = {s.id: s for s in (await session.execute(sources_stmt)).scalars().all()}

    claims_stmt = select(Claim).where(Claim.run_id == run_id)
    claims = {c.id: c for c in (await session.execute(claims_stmt)).scalars().all()}

    findings_stmt = select(Finding).where(Finding.run_id == run_id)
    db_findings = list((await session.execute(findings_stmt)).scalars().all())

    items: list[FridayFindingItem] = []

    if db_findings:
        for f in db_findings:
            citations: list[FridayCitation] = []
            claim_ids = f.claim_ids_json or []
            all_disputed = True if claim_ids else False
            finding_provenance: list[FridayProvenanceItem] = []

            for c_id in claim_ids:
                cl = claims.get(c_id)
                if cl:
                    if cl.status != ClaimStatus.DISPUTED:
                        all_disputed = False
                    src = sources.get(cl.source_id)
                    citations.append(
                        FridayCitation(
                            source_title=src.title if src and src.title else "Source Document",
                            source_url=src.location if src else "internal://source",
                            verbatim_span=cl.quote,
                        )
                    )
                    finding_provenance.append(
                        FridayProvenanceItem(
                            finding_id=f.id,
                            finding_conclusion=f.conclusion,
                            claim_id=cl.id,
                            claim_text=cl.text,
                            quote=cl.quote,
                            span_start=cl.span_start,
                            span_end=cl.span_end,
                            document_id=cl.document_id,
                            source_id=cl.source_id,
                            source_url=src.location if src else "internal://source",
                            source_title=src.title if src and src.title else "Source Document",
                            publisher=src.publisher if src else None,
                            retrieved_at=src.retrieved_at.isoformat()
                            if src and src.retrieved_at
                            else None,
                        )
                    )

            if f.contradictions_json or all_disputed:
                st = "disputed"
                is_inf = False
            elif f.confidence >= 0.70 and len(citations) > 0:
                st = "verified"
                is_inf = False
            else:
                st = "inference"
                is_inf = True

            items.append(
                FridayFindingItem(
                    finding_id=f.id,
                    statement=f.conclusion,
                    confidence_score=round(f.confidence, 4),
                    evidence_count=len(citations),
                    citations=citations,
                    status=st,
                    is_inference=is_inf,
                    provenance=finding_provenance,
                )
            )
    else:
        # Synthesize finding items directly from active claims if run completed without Finding rows
        for cl in list(claims.values())[:10]:
            src = sources.get(cl.source_id)
            cit = [
                FridayCitation(
                    source_title=src.title if src and src.title else "Source Document",
                    source_url=src.location if src else "internal://source",
                    verbatim_span=cl.quote,
                )
            ]
            st = (
                "disputed"
                if cl.status == ClaimStatus.DISPUTED
                else ("verified" if cl.confidence >= 0.75 else "inference")
            )
            is_inf = st == "inference"
            f_id = f"cl-{cl.id[:8]}"
            prov = [
                FridayProvenanceItem(
                    finding_id=f_id,
                    finding_conclusion=cl.text,
                    claim_id=cl.id,
                    claim_text=cl.text,
                    quote=cl.quote,
                    span_start=cl.span_start,
                    span_end=cl.span_end,
                    document_id=cl.document_id,
                    source_id=cl.source_id,
                    source_url=src.location if src else "internal://source",
                    source_title=src.title if src and src.title else "Source Document",
                    publisher=src.publisher if src else None,
                    retrieved_at=src.retrieved_at.isoformat()
                    if src and src.retrieved_at
                    else None,
                )
            ]
            items.append(
                FridayFindingItem(
                    finding_id=f_id,
                    statement=cl.text,
                    confidence_score=round(cl.confidence, 4),
                    evidence_count=1,
                    citations=cit,
                    status=st,
                    is_inference=is_inf,
                    provenance=prov,
                )
            )

    return FridayFindingsResponse(run_id=run_id, findings=items)


@router.get(
    "/research/{run_id}/report",
    response_model=FridayReportResponse,
    summary="Get full intelligence report in Markdown + JSON with resolved citations",
)
async def get_friday_research_report(
    run_id: str,
    session: AsyncSession = Depends(get_db_session),
    _api_key: ApiKey = Depends(get_friday_api_key),
) -> FridayReportResponse:
    """Retrieve full Markdown report and JSON intelligence payload for FRIDAY."""
    run = await RunRepo.get_run(session, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found",
        )

    # 1. Markdown Artifact
    art_md_stmt = select(Artifact).where(
        Artifact.run_id == run_id, Artifact.format == ArtifactFormat.MD
    )
    art_md = (await session.execute(art_md_stmt)).scalars().first()
    md_text = ""
    if art_md and Path(art_md.path).exists():
        md_text = Path(art_md.path).read_text(encoding="utf-8")
    else:
        md_text = f"# Research Report: {run.objective}\n\nStatus: {run.status.value}"

    # 2. JSON Artifact
    art_json_stmt = select(Artifact).where(
        Artifact.run_id == run_id, Artifact.format == ArtifactFormat.JSON
    )
    art_json = (await session.execute(art_json_stmt)).scalars().first()
    json_data: dict[str, Any] = {}
    if art_json and Path(art_json.path).exists():
        try:
            json_data = json.loads(Path(art_json.path).read_text(encoding="utf-8"))
        except Exception:
            json_data = {"run_id": run.id, "status": run.status.value}
    else:
        json_data = {
            "run_id": run.id,
            "objective": run.objective,
            "status": run.status.value,
            "outcome": run.outcome.value if run.outcome else None,
        }

    # 3. Retrieve findings and sources to build full provenance and spoken/text citations
    findings_resp = await get_friday_research_findings(run_id, session, _api_key)
    all_provenance: list[FridayProvenanceItem] = []
    for f_item in findings_resp.findings:
        all_provenance.extend(f_item.provenance)

    sources_stmt = select(Source)
    sources = list((await session.execute(sources_stmt)).scalars().all())

    spoken_summary = export_spoken_citations(findings_resp.findings, sources)
    text_response = export_text_citations(findings_resp.findings, sources)

    return FridayReportResponse(
        run_id=run.id,
        objective=run.objective,
        report_markdown=md_text,
        report_json=json_data,
        citations_resolved=True,
        spoken_summary=spoken_summary,
        text_response=text_response,
        provenance_chain=all_provenance,
    )


@router.get(
    "/research/{run_id}/events",
    summary="SSE stream pushing real-time research lifecycle events to FRIDAY",
)
async def stream_friday_research_events(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _api_key: ApiKey = Depends(get_friday_api_key),
) -> StreamingResponse:
    """Stream real-time research events via Server-Sent Events (SSE)."""
    run = await RunRepo.get_run(session, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found",
        )

    async def event_generator():
        emitted_event_ids: set[int] = set()
        loop_count = 0
        max_idle_loops = 300  # 150 seconds max streaming

        # 1. Send initial handshake event
        init_event = {
            "event": "run_started",
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": {
                "objective": run.objective,
                "status": run.status.value,
                "phase": map_run_phase(run.status),
            },
        }
        yield f"event: run_started\ndata: {json.dumps(init_event)}\n\n"

        while loop_count < max_idle_loops:
            if await request.is_disconnected():
                logger.info(f"[SSE] Client disconnected for run {run_id}")
                break

            sessionmaker = get_sessionmaker()
            async with sessionmaker() as poll_session:
                current_run = await RunRepo.get_run(poll_session, run_id)
                if not current_run:
                    break

                events = await RunRepo.get_events_for_run(poll_session, run_id)

                for ev in events:
                    if ev.id in emitted_event_ids:
                        continue

                    emitted_event_ids.add(ev.id)

                    # Map internal event types to standard FRIDAY SSE events
                    sse_type = "run_progress"
                    if "started" in ev.type:
                        sse_type = "run_started"
                    elif "subquestion" in ev.type or "plan" in ev.type:
                        sse_type = "subquestion_completed"
                    elif "source" in ev.type or "document" in ev.type or "fetch" in ev.type:
                        sse_type = "source_retrieved"
                    elif "claim" in ev.type:
                        sse_type = "claim_extracted"
                    elif "contradiction" in ev.type or "dispute" in ev.type:
                        sse_type = "contradiction_detected"
                    elif "finding" in ev.type or "confidence" in ev.type:
                        sse_type = "finding_verified"
                    elif "artifact" in ev.type or "report" in ev.type:
                        sse_type = "report_ready"

                    sse_msg = {
                        "event": sse_type,
                        "raw_type": ev.type,
                        "run_id": run_id,
                        "timestamp": ev.created_at.isoformat(),
                        "payload": ev.payload_json,
                    }
                    yield f"event: {sse_type}\ndata: {json.dumps(sse_msg)}\n\n"

                if current_run.status in (
                    RunStatus.COMPLETED,
                    RunStatus.FAILED,
                    RunStatus.CANCELLED,
                ):
                    # Final event
                    final_type = (
                        "report_ready"
                        if current_run.status == RunStatus.COMPLETED
                        else "run_terminated"
                    )
                    final_msg = {
                        "event": final_type,
                        "run_id": run_id,
                        "status": current_run.status.value,
                        "outcome": current_run.outcome.value if current_run.outcome else None,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    yield f"event: {final_type}\ndata: {json.dumps(final_msg)}\n\n"
                    break

            await asyncio.sleep(0.5)
            loop_count += 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/research/{run_id}/contradictions",
    response_model=FridayContradictionsResponse,
    summary="Get disputed claims with opposing evidence for FRIDAY presentation",
)
async def get_friday_research_contradictions(
    run_id: str,
    session: AsyncSession = Depends(get_db_session),
    _api_key: ApiKey = Depends(get_friday_api_key),
) -> FridayContradictionsResponse:
    """Return all detected factual and numeric contradictions with evidence from both sides."""
    run = await RunRepo.get_run(session, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found",
        )

    # Load all sources and claims for this run
    sources_stmt = select(Source)
    sources = {s.id: s for s in (await session.execute(sources_stmt)).scalars().all()}

    claims_stmt = select(Claim).where(Claim.run_id == run_id)
    all_claims = list((await session.execute(claims_stmt)).scalars().all())

    disputed_claims = [c for c in all_claims if c.status == ClaimStatus.DISPUTED]
    active_claims = [c for c in all_claims if c.status == ClaimStatus.ACTIVE]

    contradictions: list[FridayContradiction] = []

    # Group disputed claims by subject or pair them up
    processed_ids: set[str] = set()

    for idx, c1 in enumerate(disputed_claims):
        if c1.id in processed_ids:
            continue

        # Look for matching opposing disputed or active claim with same subject
        opposing: Claim | None = None
        for c2 in disputed_claims[idx + 1 :] + active_claims:
            if (
                c2.id != c1.id
                and c2.subject
                and c1.subject
                and (
                    c1.subject.lower() in c2.subject.lower()
                    or c2.subject.lower() in c1.subject.lower()
                )
            ):
                opposing = c2
                break

        if not opposing and len(disputed_claims) > 1:
            # Pair with next available disputed claim
            for c2 in disputed_claims:
                if c2.id != c1.id and c2.id not in processed_ids:
                    opposing = c2
                    break

        s1 = sources.get(c1.source_id)
        src1_title = s1.title if s1 and s1.title else "Primary Source"
        src1_url = s1.location if s1 else "internal://source1"

        if opposing:
            processed_ids.add(c1.id)
            processed_ids.add(opposing.id)
            s2 = sources.get(opposing.source_id)
            src2_title = s2.title if s2 and s2.title else "Opposing Source"
            src2_url = s2.location if s2 else "internal://source2"
            topic = c1.subject or opposing.subject or "Conflicting Experimental Measurement"

            contradictions.append(
                FridayContradiction(
                    contradiction_id=f"cont-{c1.id[:6]}-{opposing.id[:6]}",
                    topic_or_subject=topic,
                    claim_a=FridayClaimRef(
                        claim_id=c1.id,
                        text=c1.text,
                        quote=c1.quote,
                        source_id=c1.source_id,
                        source_title=src1_title,
                        source_url=src1_url,
                    ),
                    claim_b=FridayClaimRef(
                        claim_id=opposing.id,
                        text=opposing.text,
                        quote=opposing.quote,
                        source_id=opposing.source_id,
                        source_title=src2_title,
                        source_url=src2_url,
                    ),
                    divergence_description=f"Disputed evidence regarding {topic}",
                )
            )
        else:
            processed_ids.add(c1.id)
            contradictions.append(
                FridayContradiction(
                    contradiction_id=f"cont-{c1.id[:8]}",
                    topic_or_subject=c1.subject or "Disputed Factual Assertion",
                    claim_a=FridayClaimRef(
                        claim_id=c1.id,
                        text=c1.text,
                        quote=c1.quote,
                        source_id=c1.source_id,
                        source_title=src1_title,
                        source_url=src1_url,
                    ),
                    claim_b=FridayClaimRef(
                        claim_id=f"dispute-ref-{c1.id[:6]}",
                        text="Opposing claim or conflicting benchmark reported in corpus",
                        quote=c1.quote,
                        source_id=c1.source_id,
                        source_title=src1_title,
                        source_url=src1_url,
                    ),
                    divergence_description="Claim flagged as disputed during adversarial cross-examination",
                )
            )

    return FridayContradictionsResponse(
        run_id=run_id,
        contradiction_count=len(contradictions),
        contradictions=contradictions,
    )
