"""Main API router combining all endpoint groups."""

from fastapi import APIRouter, Depends, HTTPException

from intelx.api.v1 import v1_router
from intelx.api.v1.health import router as health_root_router
from intelx.api.v1.stratex import router as stratex_root_router
from intelx.core.auth import get_friday_api_key
from intelx.db.models import ApiKey

root_api_router = APIRouter()


def _task_receipt(
    *,
    requested_action: str,
    target: str = "intelx",
    authorization_decision: str = "AUTHORIZED",
    result: dict | None = None,
    verification_evidence: dict | None = None,
    failure_reason: str | None = None,
) -> dict:
    """Signed-in-spirit receipt for the Universal Task Protocol.

    FRIDAY's cognitive mesh refuses to call a task COMPLETED unless the peer answers
    with a receipt naming the same action it dispatched, targeting this agent, carrying
    non-empty verification evidence and no failure reason (see friday.cognition.mesh.
    verify_receipt). The schema mirrors FRIDAY's ActionReceipt so the caller can parse
    it without translation.
    """
    from datetime import datetime, timezone

    return {
        "requested_action": requested_action,
        "target": target,
        "authorization_decision": authorization_decision,
        "execution_timestamp": datetime.now(timezone.utc).isoformat(),
        "result": dict(result or {}),
        "verification_evidence": dict(verification_evidence or {}),
        "failure_reason": failure_reason,
    }

# Root health endpoints (/healthz, /readyz)
root_api_router.include_router(health_root_router)

# Versioned API routes (/api/v1/...)
root_api_router.include_router(v1_router)

# StrateX Direct Route (/v1/intelligence/research)
root_api_router.include_router(stratex_root_router, prefix="/v1")


@root_api_router.post("/v1/task/execute", tags=["Universal Task Protocol"])
async def execute_task(body: dict, api_key: ApiKey = Depends(get_friday_api_key)):
    """Universal Task Protocol endpoint for IntelX."""
    import time

    from sqlalchemy import select

    from intelx.agents.citations import export_spoken_citations, export_text_citations
    from intelx.core.enums import RunOutcome, RunStatus
    from intelx.db.models import Claim, Finding, ResearchRun, Source
    from intelx.db.session import get_sessionmaker

    t0 = time.time()
    task_id = body.get("task_id", f"intelx_{int(time.time())}")
    action = str(body.get("action", "research")).lower().strip()
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else body

    sessionmaker = get_sessionmaker()

    # 1. Action = Cancel
    if action == "cancel":
        run_id = payload.get("run_id") or payload.get("task_id") or task_id
        async with sessionmaker() as session:
            stmt = select(ResearchRun).where(
                (ResearchRun.id == run_id) | (ResearchRun.idempotency_key == run_id)
            )
            run = (await session.execute(stmt)).scalar_one_or_none()
            if run:
                key_role = getattr(api_key.role, "value", api_key.role)
                if str(key_role).lower() != "admin" and run.created_by != api_key.name:
                    raise HTTPException(status_code=404, detail="Research task not found")
                if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
                    raise HTTPException(status_code=409, detail="Research task is already terminal")
                run.status = RunStatus.CANCELLED
                run.outcome = RunOutcome.CANCELLED
                await session.commit()
                return {
                    "task_id": task_id,
                    "target_agent": "intelx",
                    "status": "CANCELLED",
                    "result": {
                        "run_id": run.id,
                        "status": "cancelled",
                        "partial_evidence_preserved": True,
                    },
                    "summary": f"Research task '{run.id}' cancelled; partial evidence preserved.",
                    "execution_time_ms": int((time.time() - t0) * 1000),
                    "receipt": _task_receipt(
                        requested_action=action,
                        authorization_decision="AUTHORIZED",
                        result={"run_id": run.id, "cancelled": True},
                        verification_evidence={
                            "run_id": run.id,
                            "run_status": "cancelled",
                            "partial_evidence_preserved": True,
                        },
                    ),
                }

    # 2. Action = Research / Query
    query = (
        payload.get("query")
        or payload.get("question")
        or payload.get("prompt")
        or payload.get("topic")
        or "Macro intelligence"
    )

    async with sessionmaker() as session:
        # Restrict summaries to completed runs owned by this integration key (or all runs for admins).
        key_role = getattr(api_key.role, "value", api_key.role)
        run_stmt = select(ResearchRun.id).where(ResearchRun.status == RunStatus.COMPLETED)
        if str(key_role).lower() != "admin":
            run_stmt = run_stmt.where(ResearchRun.created_by == api_key.name)

        query_terms = [word.strip(".,:;!?()[]{}\"'").lower() for word in query.split()]
        query_terms = [word for word in query_terms if len(word) >= 3][:6]
        if query_terms and query.lower() != "macro intelligence":
            from sqlalchemy import or_

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

        # Construct per-finding source citations from the exact supporting claims.
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
                    "statement": finding.conclusion,
                    "confidence": finding.confidence,
                    "confidence_score": finding.confidence,
                    "status": "verified" if finding.confidence >= 0.70 else "inference",
                    "claim_ids": claim_ids,
                    "citations": citations,
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
                        "statement": claim.text,
                        "confidence": claim.confidence,
                        "confidence_score": claim.confidence,
                        "status": "verified" if claim.confidence >= 0.75 else "inference",
                        "claim_ids": [claim.id],
                        "citations": citations,
                    }
                )

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

        spoken_summary = export_spoken_citations(findings_items, sources)
        text_response = export_text_citations(findings_items, sources)

    lat = int((time.time() - t0) * 1000)
    summary = f"IntelX synthesized evidence-driven research for query '{query}' with {len(sources_data)} cited sources."
    completed_run_ids = [str(run_id) for run_id in run_ids]

    return {
        "task_id": task_id,
        "target_agent": "intelx",
        "status": "SUCCESS",
        "result": {
            "query": query,
            "citations_count": len(sources_data),
            "sources": sources_data,
            "provenance_chain": provenance_chain,
            "spoken_summary": spoken_summary,
            "text_response": text_response,
            "findings_count": len(findings_items),
        },
        "summary": summary,
        "execution_time_ms": lat,
        "receipt": _task_receipt(
            requested_action=action,
            authorization_decision="AUTHORIZED",
            result={
                "query": query,
                "citations_count": len(sources_data),
                "findings_count": len(findings_items),
            },
            verification_evidence={
                "task_id": task_id,
                "completed_run_ids": completed_run_ids,
                "sources_count": len(sources_data),
                "provenance_chain_length": len(provenance_chain),
                "findings_count": len(findings_items),
                "summary": summary,
            },
        ),
    }
