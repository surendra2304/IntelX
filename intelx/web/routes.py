"""INTELX Server-Rendered Web Workspace Routes, Controllers, and Citation Resolvers."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.auth import hash_api_key
from intelx.core.enums import (
    ArtifactFormat,
    ClaimStatus,
    ReviewDecisionType,
    RunStatus,
    TrustTier,
)
from intelx.core.policy import policy_engine
from intelx.db.models import (
    ApiKey,
    Artifact,
    AuditEvent,
    Claim,
    Evidence,
    Finding,
    ResearchRun,
    ReviewDecision,
    Source,
)
from intelx.db.repos import AuditChain, RunRepo, SourceRepo
from intelx.db.session import get_sessionmaker
from intelx.web.auth import (
    COOKIE_NAME,
    get_web_user,
    require_web_user,
    sign_session_data,
)
from intelx.web.renderer import render_markdown_safe

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

web_router = APIRouter(include_in_schema=False)


async def get_db_session() -> AsyncSession:
    """Session dependency."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session


# 1. Login & Logout
@web_router.api_route("/login", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def login_page(request: Request):
    user = await get_web_user(request)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"user": None, "error": None},
    )


@web_router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    response: Response,
    api_key: str = Form(...),
    session: AsyncSession = Depends(get_db_session),
):
    key_hash = hash_api_key(api_key)
    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
    res = await session.execute(stmt)
    key_obj = res.scalar_one_or_none()

    if not key_obj:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "user": None,
                "error": "Invalid API key secret. Verification failed.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    session_payload = {
        "key_hash": key_hash,
        "name": key_obj.name,
        "role": str(key_obj.role.value if hasattr(key_obj.role, "value") else key_obj.role),
    }
    token = sign_session_data(session_payload)

    resp = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return resp


@web_router.get("/logout")
async def logout(response: Response):
    resp = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# 2. Dashboard
@web_router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(20)
    res = await session.execute(stmt)
    runs = list(res.scalars().all())

    # Calculate metrics
    stmt_total = select(func.count(ResearchRun.id))
    total_runs = (await session.execute(stmt_total)).scalar_one() or 0

    stmt_completed = select(func.count(ResearchRun.id)).where(
        ResearchRun.status == RunStatus.COMPLETED
    )
    completed_runs = (await session.execute(stmt_completed)).scalar_one() or 0

    stmt_cost = select(func.avg(ResearchRun.usd_cost))
    avg_cost = (await session.execute(stmt_cost)).scalar_one() or 0.0

    completion_rate = round((completed_runs / total_runs) * 100, 1) if total_runs > 0 else 100.0

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "active_page": "dashboard",
            "runs": runs,
            "total_runs": total_runs,
            "completed_runs": completed_runs,
            "avg_cost": avg_cost,
            "completion_rate": completion_rate,
        },
    )


# 3. New Research Form
@web_router.get("/research/new", response_class=HTMLResponse)
async def new_research_page(
    request: Request,
    user: dict[str, Any] = Depends(require_web_user),
):
    return templates.TemplateResponse(
        request=request,
        name="new_research.html",
        context={"user": user, "active_page": "new", "error": None},
    )


@web_router.post("/research/new", response_class=HTMLResponse)
async def new_research_submit(
    request: Request,
    objective: str = Form(...),
    depth: str = Form("standard"),
    max_sources: int = Form(30),
    max_usd: float = Form(5.0),
    max_minutes: int = Form(15),
    allowed_domains: str = Form(""),
    blocked_domains: str = Form(""),
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    # Policy check
    policy_dec = await policy_engine.evaluate(
        action="job.submit",
        context={"max_usd": max_usd, "actor": user["name"]},
        session=session,
    )
    if not policy_dec.allowed:
        return templates.TemplateResponse(
            request=request,
            name="new_research.html",
            context={
                "user": user,
                "active_page": "new",
                "error": f"Policy rejection: {policy_dec.reason}",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    scope_dict = {
        "depth": depth,
        "max_sources": max_sources,
        "allowed_domains": [d.strip() for d in allowed_domains.split(",") if d.strip()],
        "blocked_domains": [d.strip() for d in blocked_domains.split(",") if d.strip()],
        "budget": {"max_usd": max_usd, "max_minutes": max_minutes},
    }

    run = await RunRepo.create_run(
        session=session,
        objective=objective,
        scope_json=scope_dict,
        created_by=user["name"],
    )
    await session.commit()

    return RedirectResponse(url=f"/research/{run.id}", status_code=status.HTTP_303_SEE_OTHER)


# 4. Job Page
@web_router.get("/research/{job_id}", response_class=HTMLResponse)
async def job_page(
    job_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    run = await RunRepo.get_run(session, job_id)
    if not run:
        raise HTTPException(status_code=404, detail="Job not found")

    events = await RunRepo.get_events_for_run(session, job_id)
    return templates.TemplateResponse(
        request=request,
        name="job.html",
        context={
            "user": user,
            "active_page": "dashboard",
            "run": run,
            "events": events,
        },
    )


@web_router.post("/research/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    run = await RunRepo.get_run(session, job_id)
    if run and run.status not in (
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    ):
        run.status = RunStatus.CANCELLED
        run.completed_at = datetime.now(UTC)
        await session.commit()
    return RedirectResponse(url=f"/research/{job_id}", status_code=status.HTTP_303_SEE_OTHER)


# 5. Report Viewer Page
@web_router.get("/research/{job_id}/report", response_class=HTMLResponse)
async def report_page(
    job_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    run = await RunRepo.get_run(session, job_id)
    if not run:
        raise HTTPException(status_code=404, detail="Job not found")

    # Load artifacts
    stmt_art = select(Artifact).where(Artifact.run_id == job_id)
    artifacts = list((await session.execute(stmt_art)).scalars().all())

    # Read report markdown content safely
    report_md_art = next((a for a in artifacts if a.format == ArtifactFormat.MD), None)
    if report_md_art and Path(report_md_art.path).exists():
        raw_md = Path(report_md_art.path).read_text(encoding="utf-8")
    else:
        raw_md = (
            f"# Research Report: {run.objective}\n\n"
            "## Direct Answer\nSynthesis in progress or unavailable."
        )

    safe_html = render_markdown_safe(raw_md)

    # Load claims and sources for tabs
    stmt_claims = select(Claim).where(Claim.run_id == job_id)
    claims = list((await session.execute(stmt_claims)).scalars().all())
    disputed_claims = [c for c in claims if c.status == ClaimStatus.DISPUTED]

    stmt_sources = select(Source).where(Source.created_by_run_id == job_id)
    sources = list((await session.execute(stmt_sources)).scalars().all())

    stmt_findings = select(Finding).where(Finding.run_id == job_id)
    findings = list((await session.execute(stmt_findings)).scalars().all())

    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={
            "user": user,
            "active_page": "dashboard",
            "run": run,
            "report_html": safe_html,
            "artifacts": artifacts,
            "claims": claims,
            "disputed_claims": disputed_claims,
            "sources": sources,
            "findings": findings,
        },
    )


# 6. Citation Inspection Endpoint (JSON for drawer)
@web_router.get("/api/citation/{kind}/{token}")
async def get_citation_data(
    kind: str,
    token: str,
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    if kind.upper() == "S":
        stmt = select(Source).where(Source.id.startswith(token))
        res = await session.execute(stmt)
        source = res.scalars().first()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        return {
            "id": source.id,
            "title": source.title,
            "domain": source.domain,
            "trust_tier": str(
                source.trust_tier.value
                if hasattr(source.trust_tier, "value")
                else source.trust_tier
            ),
            "retrieved_at": source.retrieved_at.isoformat() if source.retrieved_at else None,
            "fingerprint": source.fingerprint,
            "injection_risk": source.injection_risk,
            "location": source.location,
        }
    elif kind.upper() == "C":
        stmt = select(Claim).where(Claim.id.startswith(token))
        res = await session.execute(stmt)
        claim = res.scalars().first()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")

        stmt_ev = select(Evidence).where(Evidence.claim_id == claim.id)
        evidence_items = list((await session.execute(stmt_ev)).scalars().all())

        return {
            "id": claim.id,
            "text": claim.text,
            "claim_type": str(
                claim.claim_type.value if hasattr(claim.claim_type, "value") else claim.claim_type
            ),
            "confidence": claim.confidence,
            "status": str(claim.status.value if hasattr(claim.status, "value") else claim.status),
            "evidence": [
                {"id": e.id, "source_id": e.source_id, "quote": e.quote} for e in evidence_items
            ],
        }
    raise HTTPException(status_code=400, detail="Invalid citation kind")


# 7. Review Queue (Admin)
@web_router.get("/review", response_class=HTMLResponse)
async def review_queue_page(
    request: Request,
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin role required")

    stmt_runs = select(ResearchRun).where(ResearchRun.status == RunStatus.REVIEW_REQUIRED)
    review_runs = list((await session.execute(stmt_runs)).scalars().all())

    stmt_sources = select(Source).where(Source.trust_tier == TrustTier.QUARANTINE)
    quarantine_sources = list((await session.execute(stmt_sources)).scalars().all())

    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={
            "user": user,
            "active_page": "review",
            "review_runs": review_runs,
            "quarantine_sources": quarantine_sources,
        },
    )


@web_router.post("/review/job/{job_id}")
async def review_job_decision(
    job_id: str,
    decision: str = Form(...),
    notes: str = Form(""),
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin role required")

    run = await RunRepo.get_run(session, job_id)
    if run:
        dec_obj = ReviewDecision(
            run_id=job_id,
            decision=ReviewDecisionType(decision),
            notes=notes,
            decided_by=user["name"],
        )
        session.add(dec_obj)
        run.scope_json = run.scope_json or {}
        run.scope_json["review_decision"] = decision
        run.status = RunStatus.QUEUED

        await AuditChain.append_event(
            session=session,
            actor=user["name"],
            action="review.decided",
            object_type="research_run",
            object_id=job_id,
            detail_json={"decision": decision, "notes": notes},
        )
        await session.commit()
    return RedirectResponse(url="/review", status_code=status.HTTP_303_SEE_OTHER)


@web_router.post("/review/source/{source_id}")
async def review_source_decision(
    source_id: str,
    tier: str = Form(...),
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin role required")

    await SourceRepo.set_trust(session, source_id, TrustTier(tier))
    await AuditChain.append_event(
        session=session,
        actor=user["name"],
        action="source.trust_updated",
        object_type="source",
        object_id=source_id,
        detail_json={"tier": tier},
    )
    await session.commit()
    return RedirectResponse(url="/review", status_code=status.HTTP_303_SEE_OTHER)


# 8. Knowledge Search Page
@web_router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(
    request: Request,
    q: str = "",
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    results = []
    if q.strip():
        results = await SourceRepo.search_full_text(session, query=q.strip(), limit=20)

    return templates.TemplateResponse(
        request=request,
        name="knowledge.html",
        context={
            "user": user,
            "active_page": "knowledge",
            "query": q,
            "results": results,
        },
    )


# 9. Admin Audit Ledger Page
@web_router.get("/admin/audit", response_class=HTMLResponse)
async def admin_audit_page(
    request: Request,
    user: dict[str, Any] = Depends(require_web_user),
    session: AsyncSession = Depends(get_db_session),
):
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin role required")

    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(100)
    res = await session.execute(stmt)
    events = list(res.scalars().all())

    is_valid, _ = await AuditChain.verify(session)

    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={
            "user": user,
            "active_page": "audit",
            "events": events,
            "chain_valid": is_valid,
        },
    )
