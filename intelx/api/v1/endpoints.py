"""INTELX Versioned REST API Surface (v1.0), OpenAPI Documentation, and Routes."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.auth import get_current_api_key, require_role
from intelx.core.enums import (
    ApiKeyRole,
    ArtifactFormat,
    ClaimStatus,
    ReviewDecisionType,
    RunStatus,
    TrustTier,
)
from intelx.core.policy import PolicyConfig, policy_engine
from intelx.db.models import (
    ApiKey,
    Artifact,
    AuditEvent,
    Event,
    ResearchRun,
    ReviewDecision,
)
from intelx.db.repos import AuditChain, ClaimRepo, RunRepo, SourceRepo
from intelx.db.session import get_sessionmaker
from intelx.orchestration.events import EventStreamManager, emit_event

router = APIRouter(tags=["Research & Intelligence v1"])


async def get_db_session() -> AsyncSession:
    """FastAPI database session dependency."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session


# Schemas
class ScopeModel(BaseModel):
    depth: str = Field(default="standard", description="Research depth: quick | standard | deep")
    time_range: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    max_sources: int = 50
    output_format: str = "markdown"


class BudgetModel(BaseModel):
    max_usd: float = 10.0
    max_minutes: int = 30


class CreateJobRequest(BaseModel):
    objective: str = Field(..., min_length=5, description="Primary research objective question")
    scope: ScopeModel = Field(default_factory=ScopeModel)
    budget: BudgetModel = Field(default_factory=BudgetModel)


class JobResponse(BaseModel):
    id: str
    objective: str
    status: str
    outcome: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    usd_cost: float = 0.0
    tool_calls: int = 0


class FollowupRequest(BaseModel):
    focus: str = Field(..., min_length=5, description="Followup extension focus query")
    challenge_existing: bool = True


class ReviewRequest(BaseModel):
    decision: ReviewDecisionType
    notes: str | None = None


class TrustUpdateRequest(BaseModel):
    tier: TrustTier


class RetractClaimRequest(BaseModel):
    reason: str = Field(..., min_length=5)
    superseded_by: str | None = None


class KnowledgeQueryRequest(BaseModel):
    q: str = Field(..., min_length=2)
    kinds: list[str] = Field(default_factory=lambda: ["claim", "source", "entity"])
    limit: int = 10


# 1. Job Submission
@router.post(
    "/research/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a new research investigation",
)
async def create_research_job(
    req: CreateJobRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    api_key: ApiKey = Depends(get_current_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    # Idempotency Check
    if idempotency_key:
        stmt = select(ResearchRun).where(ResearchRun.idempotency_key == idempotency_key)
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            created_ts = existing.created_at
            if created_ts.tzinfo is None:
                created_ts = created_ts.replace(tzinfo=UTC)
            if created_ts >= datetime.now(UTC) - timedelta(hours=24):
                response.status_code = status.HTTP_200_OK
                return JobResponse(
                    id=existing.id,
                    objective=existing.objective,
                    status=str(existing.status),
                    outcome=str(existing.outcome) if existing.outcome else None,
                    created_at=existing.created_at.isoformat(),
                    started_at=existing.started_at.isoformat() if existing.started_at else None,
                    completed_at=existing.completed_at.isoformat()
                    if existing.completed_at
                    else None,
                    input_tokens=existing.input_tokens,
                    output_tokens=existing.output_tokens,
                    usd_cost=existing.usd_cost,
                    tool_calls=existing.tool_calls,
                )

    # Policy Evaluation
    policy_dec = await policy_engine.evaluate(
        action="job.submit",
        context={"max_usd": req.budget.max_usd, "actor": api_key.name},
        session=session,
    )
    if not policy_dec.allowed:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job rejected by policy: {policy_dec.reason}",
        )

    scope_dict = req.scope.model_dump()
    scope_dict["budget"] = req.budget.model_dump()

    run = await RunRepo.create_run(
        session=session,
        objective=req.objective,
        scope_json=scope_dict,
        created_by=api_key.name,
        idempotency_key=idempotency_key,
    )
    await session.commit()

    return JobResponse(
        id=run.id,
        objective=run.objective,
        status=str(run.status),
        outcome=None,
        created_at=run.created_at.isoformat(),
        started_at=None,
        completed_at=None,
        input_tokens=0,
        output_tokens=0,
        usd_cost=0.0,
        tool_calls=0,
    )


# 2. List Jobs
@router.get(
    "/research/jobs",
    summary="List research runs with cursor pagination",
)
async def list_research_jobs(
    status_filter: RunStatus | None = Query(None, alias="status"),
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    api_key: ApiKey = Depends(get_current_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(ResearchRun)
    if status_filter:
        stmt = stmt.where(ResearchRun.status == status_filter)
    if cursor:
        stmt = stmt.where(ResearchRun.id < cursor)
    stmt = stmt.order_by(ResearchRun.created_at.desc()).limit(limit + 1)

    res = await session.execute(stmt)
    runs = list(res.scalars().all())
    has_more = len(runs) > limit
    returned_runs = runs[:limit]
    next_cursor = returned_runs[-1].id if has_more and returned_runs else None

    return {
        "items": [
            {
                "id": r.id,
                "objective": r.objective,
                "status": str(r.status),
                "outcome": str(r.outcome) if r.outcome else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in returned_runs
        ],
        "next_cursor": next_cursor,
    }


# 3. Get Job
@router.get("/research/jobs/{job_id}", summary="Retrieve job details")
async def get_research_job(
    job_id: str,
    api_key: ApiKey = Depends(get_current_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    run = await RunRepo.get_run(session, job_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {
        "id": run.id,
        "objective": run.objective,
        "status": str(run.status),
        "outcome": str(run.outcome) if run.outcome else None,
        "scope": run.scope_json,
        "plan": run.plan_json,
        "error": run.error_json,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "usd_cost": run.usd_cost,
        "tool_calls": run.tool_calls,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


# 4. Cancel Job
@router.post("/research/jobs/{job_id}/cancel", summary="Cancel an active research job")
async def cancel_research_job(
    job_id: str,
    api_key: ApiKey = Depends(get_current_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    run = await RunRepo.get_run(session, job_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job {job_id} cannot be cancelled in terminal state '{run.status}'",
        )

    run.status = RunStatus.CANCELLED
    run.error_json = {"cancel_requested": True, "cancelled_by": api_key.name}
    run.completed_at = datetime.now(UTC)
    await session.commit()
    await emit_event(session, job_id, "run.cancelled", {"cancelled_by": api_key.name})

    return {"status": "CANCELLED", "id": job_id}


# 5. Events (Polling + SSE)
@router.get("/research/jobs/{job_id}/events", summary="Stream or poll job telemetry events")
async def get_job_events(
    job_id: str,
    request: Request,
    after: int = Query(0, description="Return events with id > after"),
    stream: bool = Query(False, description="Stream events via SSE"),
    api_key: ApiKey = Depends(get_current_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    accept_header = request.headers.get("accept", "")
    if stream or "text/event-stream" in accept_header:

        async def _event_generator():
            async for ev in EventStreamManager.iterate_events(job_id):
                yield f"data: {json.dumps(ev)}\n\n"

        return StreamingResponse(_event_generator(), media_type="text/event-stream")

    stmt = select(Event).where(Event.run_id == job_id, Event.id > after).order_by(Event.id.asc())
    res = await session.execute(stmt)
    events = list(res.scalars().all())
    return [
        {
            "id": e.id,
            "run_id": e.run_id,
            "type": e.type,
            "payload": e.payload_json,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]


# 6. Artifacts List
@router.get("/research/jobs/{job_id}/artifacts", summary="List artifacts for a research run")
async def list_job_artifacts(
    job_id: str,
    api_key: ApiKey = Depends(get_current_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(Artifact).where(Artifact.run_id == job_id)
    res = await session.execute(stmt)
    artifacts = list(res.scalars().all())
    return [
        {
            "id": a.id,
            "run_id": a.run_id,
            "type": str(a.type),
            "format": str(a.format),
            "path": a.path,
            "sha256": a.sha256,
            "schema_version": a.schema_version,
            "created_at": a.created_at.isoformat(),
        }
        for a in artifacts
    ]


# 7. Download Artifact
@router.get("/artifacts/{artifact_id}", summary="Download specific artifact file")
async def download_artifact(
    artifact_id: str,
    format_opt: str | None = Query(None, alias="format"),
    api_key: ApiKey = Depends(get_current_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(Artifact).where(Artifact.id == artifact_id)
    res = await session.execute(stmt)
    art = res.scalar_one_or_none()
    if not art:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    file_path = Path(art.path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing from storage")

    media_map = {
        ArtifactFormat.MD: "text/markdown",
        ArtifactFormat.JSON: "application/json",
        ArtifactFormat.CSV: "text/csv",
    }
    media_type = media_map.get(art.format, "application/octet-stream")
    return FileResponse(path=file_path, media_type=media_type, filename=file_path.name)


# 8. Followups
@router.post(
    "/research/jobs/{job_id}/followups",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a followup research run extending previous findings",
)
async def create_followup_job(
    job_id: str,
    req: FollowupRequest,
    api_key: ApiKey = Depends(get_current_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    parent_run = await RunRepo.get_run(session, job_id)
    if not parent_run:
        raise HTTPException(status_code=404, detail=f"Parent job {job_id} not found")

    scope_dict = {
        "depth": "standard",
        "parent_run_id": job_id,
        "challenge_existing": req.challenge_existing,
    }

    child_run = await RunRepo.create_run(
        session=session,
        objective=f"Followup: {req.focus}",
        scope_json=scope_dict,
        parent_run_id=job_id,
        created_by=api_key.name,
    )
    await session.commit()

    return JobResponse(
        id=child_run.id,
        objective=child_run.objective,
        status=str(child_run.status),
        created_at=child_run.created_at.isoformat(),
    )


# 9. Review Gate (Admin)
@router.post(
    "/research/jobs/{job_id}/review",
    summary="Post human review decision and resume paused run (Admin)",
)
async def post_review_decision(
    job_id: str,
    req: ReviewRequest,
    admin_key: ApiKey = Depends(require_role(ApiKeyRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
):
    run = await RunRepo.get_run(session, job_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    decision = ReviewDecision(
        run_id=job_id,
        decision=req.decision,
        notes=req.notes,
        decided_by=admin_key.name,
    )
    session.add(decision)

    await AuditChain.append_event(
        session=session,
        actor=admin_key.name,
        action="review.decided",
        object_type="research_run",
        object_id=job_id,
        detail_json={"decision": str(req.decision), "notes": req.notes},
    )

    if run.status == RunStatus.REVIEW_REQUIRED:
        run.scope_json = run.scope_json or {}
        run.scope_json["review_decision"] = str(req.decision)
        run.status = RunStatus.QUEUED

    await session.commit()
    return {"status": "recorded", "decision": str(req.decision), "job_id": job_id}


# 10. Knowledge Query
@router.post("/knowledge/query", summary="Search knowledge base using full-text search")
async def query_knowledge(
    req: KnowledgeQueryRequest,
    api_key: ApiKey = Depends(get_current_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    results = await SourceRepo.search_full_text(session, query=req.q, limit=req.limit)
    return {
        "query": req.q,
        "count": len(results),
        "results": results,
    }


# 11. Sources & Trust
@router.get("/sources/{source_id}", summary="Retrieve source metadata")
async def get_source(
    source_id: str,
    api_key: ApiKey = Depends(get_current_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    source = await SourceRepo.get_source(session, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    return {
        "id": source.id,
        "kind": str(source.kind),
        "location": source.location,
        "domain": source.domain,
        "publisher": source.publisher,
        "title": source.title,
        "trust_tier": str(source.trust_tier),
        "fingerprint": source.fingerprint,
        "injection_risk": source.injection_risk,
        "retrieved_at": source.retrieved_at.isoformat(),
    }


@router.post("/sources/{source_id}/trust", summary="Update source trust tier (Admin)")
async def update_source_trust(
    source_id: str,
    req: TrustUpdateRequest,
    admin_key: ApiKey = Depends(require_role(ApiKeyRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
):
    source = await SourceRepo.set_trust(session, source_id, req.tier)
    await AuditChain.append_event(
        session=session,
        actor=admin_key.name,
        action="source.trust_updated",
        object_type="source",
        object_id=source_id,
        detail_json={"new_tier": str(req.tier)},
    )
    await session.commit()
    return {"id": source.id, "trust_tier": str(source.trust_tier)}


# 12. Claim Retraction
@router.post("/knowledge/claims/{claim_id}/retract", summary="Retract an erroneous claim (Admin)")
async def retract_claim(
    claim_id: str,
    req: RetractClaimRequest,
    admin_key: ApiKey = Depends(require_role(ApiKeyRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
):
    claim = await ClaimRepo.get_claim(session, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")

    claim.status = ClaimStatus.RETRACTED
    claim.retraction_reason = req.reason
    if req.superseded_by:
        claim.superseded_by = req.superseded_by

    await AuditChain.append_event(
        session=session,
        actor=admin_key.name,
        action="claim.retracted",
        object_type="claim",
        object_id=claim_id,
        detail_json={"reason": req.reason, "superseded_by": req.superseded_by},
    )
    await session.commit()
    return {"id": claim.id, "status": "RETRACTED", "reason": req.reason}


# 13. Policy Management
@router.get("/policies", summary="Retrieve active policy configuration (Admin)")
async def get_policies(
    admin_key: ApiKey = Depends(require_role(ApiKeyRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
):
    cfg, version = await policy_engine.get_config(session)
    return {"version": version, "config": cfg.model_dump()}


@router.put("/policies", summary="Update policy configuration (Admin)")
async def update_policies(
    new_config: PolicyConfig,
    admin_key: ApiKey = Depends(require_role(ApiKeyRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
):
    policy_row = await policy_engine.update_config(session, new_config, admin_key.name)
    await session.commit()
    return {"version": policy_row.version, "config": new_config.model_dump()}


# 14. Audit Ledger
@router.get("/audit", summary="Get paginated audit trail records (Admin)")
async def get_audit_trail(
    limit: int = Query(50, ge=1, le=200),
    cursor: int | None = None,
    admin_key: ApiKey = Depends(require_role(ApiKeyRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(AuditEvent)
    if cursor:
        stmt = stmt.where(AuditEvent.id < cursor)
    stmt = stmt.order_by(AuditEvent.id.desc()).limit(limit)

    res = await session.execute(stmt)
    events = list(res.scalars().all())
    return [
        {
            "id": e.id,
            "ts": e.ts.isoformat(),
            "actor": e.actor,
            "action": e.action,
            "object_type": e.object_type,
            "object_id": e.object_id,
            "detail": e.detail_json,
            "hash": e.hash,
            "prev_hash": e.prev_hash,
        }
        for e in events
    ]


@router.get("/audit/verify", summary="Verify cryptographic integrity of audit chain (Admin)")
async def verify_audit_ledger(
    admin_key: ApiKey = Depends(require_role(ApiKeyRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
):
    is_valid, errors = await AuditChain.verify(session)
    return {
        "valid": is_valid,
        "errors": errors,
        "verified_at": datetime.now(UTC).isoformat(),
    }
