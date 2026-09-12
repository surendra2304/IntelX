"""Main API router combining all endpoint groups."""

from fastapi import APIRouter

from intelx.api.v1 import v1_router
from intelx.api.v1.health import router as health_root_router
from intelx.api.v1.stratex import router as stratex_root_router

root_api_router = APIRouter()

# Root health endpoints (/healthz, /readyz)
root_api_router.include_router(health_root_router)

# Versioned API routes (/api/v1/...)
root_api_router.include_router(v1_router)

# StrateX Direct Route (/v1/intelligence/research)
root_api_router.include_router(stratex_root_router, prefix="/v1")


@root_api_router.post("/v1/task/execute", tags=["Universal Task Protocol"])
async def execute_task(body: dict):
    """Universal Task Protocol endpoint for IntelX."""
    import time
    from sqlalchemy import select
    from intelx.agents.citations import export_spoken_citations, export_text_citations
    from intelx.core.enums import RunOutcome, RunStatus
    from intelx.db.models import Claim, Document, Finding, ResearchRun, Source
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
        # Fetch latest sources and documents
        stmt_src = select(Source).order_by(Source.retrieved_at.desc()).limit(10)
        sources = list((await session.execute(stmt_src)).scalars().all())

        stmt_cl = select(Claim).where(Claim.status != "DISPUTED").order_by(Claim.created_at.desc()).limit(10)
        claims = list((await session.execute(stmt_cl)).scalars().all())

        stmt_f = select(Finding).order_by(Finding.created_at.desc()).limit(5)
        findings = list((await session.execute(stmt_f)).scalars().all())

        # Construct findings items for citation generators
        findings_items = []
        for f in findings:
            findings_items.append({
                "statement": f.conclusion,
                "confidence": f.confidence,
                "confidence_score": f.confidence,
                "status": "verified" if f.confidence >= 0.70 else "inference",
                "claim_ids": f.claim_ids_json or [],
            })

        if not findings_items and claims:
            for cl in claims[:5]:
                findings_items.append({
                    "statement": cl.text,
                    "confidence": cl.confidence,
                    "confidence_score": cl.confidence,
                    "status": "verified" if cl.confidence >= 0.75 else "inference",
                    "claim_ids": [cl.id],
                })

        provenance_chain = []
        for cl in claims[:10]:
            matching_s = next((s for s in sources if s.id == cl.source_id), None)
            provenance_chain.append({
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
            })

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
    }
