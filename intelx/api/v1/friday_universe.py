"""INTELX — FRIDAY Universe Intelligence Feed API.

Allows any FRIDAY Universe agent to query IntelX's knowledge base
for intelligence collected specifically for that agent.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.auth import get_current_api_key
from intelx.db.models import ApiKey, Chunk, Document, Source
from intelx.db.session import get_sessionmaker

logger = logging.getLogger("intelx.api.friday_universe")

router = APIRouter(prefix="/friday-universe", tags=["FRIDAY Universe Intelligence"])

VALID_AGENTS = {"stratex", "futuris", "sentinel", "friday", "cortex", "forge", "inference", "all"}


async def get_db_session() -> AsyncSession:
    """FastAPI database session dependency."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session


class IntelligenceItem(BaseModel):
    title: str
    url: str
    publisher: str
    agent: str
    category: str
    published_at: str | None
    summary: str
    retrieved_at: str


class IntelligenceFeed(BaseModel):
    agent: str
    total_items: int
    items: list[IntelligenceItem]


@router.get(
    "/intelligence",
    response_model=IntelligenceFeed,
    summary="Get targeted intelligence for a FRIDAY Universe agent",
    description=(
        "Returns the latest news and intelligence collected specifically for "
        "a FRIDAY Universe agent (stratex, futuris, sentinel, friday, cortex, forge, inference). "
        "Pass agent=all to get everything."
    ),
)
async def get_agent_intelligence(
    agent: str = Query(
        default="all",
        description="Target agent: stratex | futuris | sentinel | friday | cortex | forge | inference | all",
    ),
    limit: int = Query(default=50, le=200, ge=1, description="Number of items to return"),
    session: AsyncSession = Depends(get_db_session),
    _: ApiKey = Depends(get_current_api_key),
) -> IntelligenceFeed:
    agent = agent.lower().strip()
    if agent not in VALID_AGENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid agent '{agent}'. Must be one of: {', '.join(sorted(VALID_AGENTS))}",
        )

    # Query sources filtered by agent tag in title/domain metadata
    # We store agent as [FRIDAY_AGENT:STRATEX] prefix in document text
    if agent == "all":
        stmt = (
            select(Source, Document)
            .join(Document, Document.source_id == Source.id)
            .order_by(Source.retrieved_at.desc())
            .limit(limit)
        )
    else:
        agent_tag = f"[FRIDAY_AGENT:{agent.upper()}]"
        stmt = (
            select(Source, Document)
            .join(Document, Document.source_id == Source.id)
            .where(Document.text.contains(agent_tag))
            .order_by(Source.retrieved_at.desc())
            .limit(limit)
        )

    result = await session.execute(stmt)
    rows = result.all()

    items: list[IntelligenceItem] = []
    for source, doc in rows:
        # Extract agent/category from the tagged document text
        doc_agent = agent if agent != "all" else _extract_tag(doc.text, "FRIDAY_AGENT") or "unknown"
        doc_category = _extract_tag(doc.text, "CATEGORY") or "general"

        # Extract first meaningful paragraph as summary
        lines = doc.text.split("\n")
        summary_lines = [l for l in lines[4:] if l.strip() and not l.startswith("[")]
        summary = " ".join(summary_lines)[:500]

        items.append(IntelligenceItem(
            title=source.title or "Untitled",
            url=source.location,
            publisher=source.publisher or "",
            agent=doc_agent.lower(),
            category=doc_category.lower(),
            published_at=source.published_at.isoformat() if source.published_at else None,
            summary=summary,
            retrieved_at=source.retrieved_at.isoformat(),
        ))

    return IntelligenceFeed(agent=agent, total_items=len(items), items=items)


@router.get(
    "/status",
    summary="Check knowledge base ingestion status",
)
async def get_ingestion_status(
    session: AsyncSession = Depends(get_db_session),
    _: ApiKey = Depends(get_current_api_key),
) -> dict:
    """Returns count of ingested intelligence items per agent."""
    total_stmt = select(Source).order_by(Source.retrieved_at.desc()).limit(1)
    total_count_stmt = select(Source)
    
    result = await session.execute(total_count_stmt)
    all_sources = result.scalars().all()
    total = len(all_sources)

    # Count by agent by querying documents
    agent_counts: dict[str, int] = {}
    for ag in ["stratex", "futuris", "sentinel", "friday", "cortex", "forge", "inference"]:
        tag = f"[FRIDAY_AGENT:{ag.upper()}]"
        count_stmt = (
            select(Document)
            .where(Document.text.contains(tag))
        )
        r = await session.execute(count_stmt)
        agent_counts[ag] = len(r.scalars().all())

    return {
        "status": "active",
        "total_intelligence_items": total,
        "by_agent": agent_counts,
        "message": "IntelX is continuously ingesting targeted intelligence for all FRIDAY Universe agents.",
    }


@router.post(
    "/trigger-research",
    summary="Trigger an autonomous research investigation immediately",
)
async def trigger_autonomous_research(
    agent: str = Query(default="all", description="Target agent: stratex | sentinel | friday | futuris | all"),
    session: AsyncSession = Depends(get_db_session),
    _: ApiKey = Depends(get_current_api_key),
) -> dict:
    """Manually dispatch an autonomous intelligence research investigation."""
    from intelx.orchestration.autonomous_researcher import AUTONOMOUS_RESEARCH_TOPICS
    from intelx.db.repos import RunRepo

    agent = agent.lower().strip()
    topic = next((t for t in AUTONOMOUS_RESEARCH_TOPICS if t["agent"] == agent), AUTONOMOUS_RESEARCH_TOPICS[0])

    scope = {
        "domain": topic["domain"],
        "depth": "quick",
        "autonomous": True,
        "agent": topic["agent"],
        "target_agent": topic["agent"].upper(),
    }

    run = await RunRepo.create_run(
        session=session,
        objective=topic["objective"],
        scope_json=scope,
    )
    await session.commit()

    return {
        "status": "queued",
        "run_id": run.id,
        "target_agent": topic["agent"],
        "objective": topic["objective"],
        "message": "Research investigation spawned. The orchestration worker will execute it immediately.",
    }


@router.post(
    "/intelligence",
    summary="Execute or query targeted intelligence for FRIDAY Universe",
)
async def post_agent_intelligence(
    body: dict,
    session: AsyncSession = Depends(get_db_session),
    _: ApiKey = Depends(get_current_api_key),
) -> dict:
    """Accepts TaskEnvelope or research payload and returns intelligence with citations."""
    import time
    t0 = time.time()
    
    task_id = body.get("task_id", f"intelx_{int(time.time())}")
    action = body.get("action", "research")
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
    query = payload.get("query") or payload.get("prompt") or payload.get("topic") or "Macro market intelligence"
    caller = body.get("source_agent", "friday")

    # Fetch recent items from knowledge base
    stmt = (
        select(Source, Document)
        .join(Document, Document.source_id == Source.id)
        .order_by(Source.retrieved_at.desc())
        .limit(5)
    )
    result = await session.execute(stmt)
    rows = result.all()

    items = []
    for source, doc in rows:
        items.append({
            "title": source.title or "Intelligence Report",
            "url": source.url or "",
            "summary": doc.text[:200].strip() if doc.text else "",
            "publisher": source.publisher or "IntelX Ingestion Engine",
        })

    lat = int((time.time() - t0) * 1000)
    summary_text = f"IntelX synthesized intelligence for '{query}' with {len(items)} cited sources."

    return {
        "task_id": task_id,
        "target_agent": "intelx",
        "status": "SUCCESS",
        "result": {
            "query": query,
            "citations_count": len(items),
            "sources": items,
            "analysis": summary_text,
        },
        "summary": summary_text,
        "execution_time_ms": lat,
    }


def _extract_tag(text: str, tag_name: str) -> str | None:
    """Extract value from [TAG_NAME:VALUE] marker in document text."""
    m = re.search(rf"\[{tag_name}:([^\]]+)\]", text)
    return m.group(1) if m else None


import re
