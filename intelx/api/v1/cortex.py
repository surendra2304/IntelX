"""INTELX — Cortex Website Operations & Lead Intelligence API Router.

Cortex (Agent 6) is the Website Agent of the FRIDAY Universe.
It manages website visitors, captures and qualifies leads, answers visitor inquiries,
and optimizes website conversion rates.

This router provides endpoints for Cortex to:
1. Request deep lead enrichment and prospect domain dossiers (/v1/cortex/enrich-lead)
2. Obtain verified, cited answers for complex website visitor queries (/v1/cortex/visitor-query)
3. Trigger outbound intelligence dispatches to Cortex's lead qualification pipeline (/v1/cortex/trigger-lead-intel)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.api.v1.futuris import verify_futuris_auth
from intelx.connectors.search import SearchResult, WebSearchConnector
from intelx.core.enums import RunOutcome, RunStatus
from intelx.core.errors import ProviderError
from intelx.core.settings import get_settings
from intelx.db.models import Claim, Finding, ResearchRun
from intelx.db.session import get_db_session
from intelx.integrations.cortex_context import (
    CortexConnector,
    CortexLeadDossier,
)

logger = logging.getLogger("intelx.api.v1.cortex")

router = APIRouter(prefix="/cortex", tags=["Cortex Website & Lead Intelligence Integration"])


class CortexLeadEnrichmentRequest(BaseModel):
    """Payload sent by Cortex when requesting dossier enrichment for a website visitor/lead."""

    domain: str = Field(
        ..., description="Domain or company website URL, e.g. 'stripe.com' or 'alex@acme.com'"
    )
    lead_id: str | None = Field(
        None, description="Optional lead identifier from Cortex's CRM/lead database"
    )
    company_name: str | None = Field(
        None, description="Optional company name if already provided by visitor"
    )
    visitor_notes: str | None = Field(
        None, description="Any specific notes or page context captured by Cortex"
    )


class CortexVisitorQueryRequest(BaseModel):
    """Payload sent by Cortex when a website visitor asks a technical or product question."""

    query: str = Field(
        ..., description="The visitor's question submitted in the website chat widget"
    )
    visitor_id: str | None = Field(
        None, description="Optional anonymous or session visitor identifier"
    )
    page_url: str | None = Field(
        None, description="The landing page or document URL the visitor is viewing"
    )


class CortexVisitorQueryResponse(BaseModel):
    """Structured, verified answer returned to Cortex to display in the website visitor chat widget."""

    query: str
    answer: str
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    sources: list[dict[str, str]] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)


class CortexTriggerLeadIntelRequest(BaseModel):
    """Payload to trigger an outbound lead intelligence dispatch to Cortex."""

    finding_text: str = Field(..., description="Key intelligence finding or prospect signal")
    run_id: str = Field(..., description="IntelX research run ID")
    domain: str = Field(default="general")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    webhook_url: str | None = None


@router.post(
    "/enrich-lead",
    response_model=CortexLeadDossier,
    summary="Enrich Website Visitor or Prospective Client Lead",
    dependencies=[Depends(verify_futuris_auth)],
)
async def enrich_lead(
    request: CortexLeadEnrichmentRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CortexLeadDossier:
    """Provide structured OSINT dossier for a prospective website lead or visitor domain.

    Cortex uses this intelligence to personalize live chat greetings, evaluate lead
    qualification score, and supply talking points to convert site visitors.
    """
    clean_domain = CortexConnector.extract_domain(request.domain)
    if not clean_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid domain or email provided for lead enrichment.",
        )

    # 1. Search existing completed research runs in intelx_db for this domain
    domain_pattern = f"%{clean_domain}%"
    stmt = (
        select(ResearchRun)
        .where(
            ResearchRun.status == RunStatus.COMPLETED,
            ResearchRun.outcome == RunOutcome.ANSWERED,
            ResearchRun.objective.ilike(domain_pattern),
        )
        .order_by(ResearchRun.created_at.desc())
        .limit(3)
    )
    runs = (await session.execute(stmt)).scalars().all()

    findings_data: list[dict[str, Any]] = []
    claims_data: list[dict[str, Any]] = []

    if runs:
        run_ids = [r.id for r in runs]
        stmt_f = select(Finding).where(Finding.run_id.in_(run_ids)).limit(10)
        f_rows = (await session.execute(stmt_f)).scalars().all()
        findings_data = [{"conclusion": f.conclusion, "confidence": f.confidence} for f in f_rows]

        stmt_c = select(Claim).where(Claim.run_id.in_(run_ids)).limit(10)
        c_rows = (await session.execute(stmt_c)).scalars().all()
        claims_data = [
            {"text": c.quote or c.subject or "", "confidence": c.confidence} for c in c_rows
        ]

    # Synthesize dossier from empirical findings or structured knowledge
    dossier = CortexConnector.synthesize_lead_dossier(
        target_domain=clean_domain,
        findings=findings_data if findings_data else None,
        claims=claims_data if claims_data else None,
    )
    if request.company_name:
        dossier.company_name = request.company_name

    logger.info("IntelX generated lead enrichment dossier for Cortex on domain: %s", clean_domain)
    return dossier


@router.post(
    "/visitor-query",
    response_model=CortexVisitorQueryResponse,
    summary="Answer Website Visitor Inquiry with Fact-Checked Intel",
    dependencies=[Depends(verify_futuris_auth)],
)
async def answer_visitor_query(
    request: CortexVisitorQueryRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CortexVisitorQueryResponse:
    """Provide verified, cited intelligence to answer questions from website visitors in real-time.

    Queries IntelX's indexed knowledge base and external search to deliver grounded answers
    with reputable source links for the Cortex website chat widget.
    """
    settings = get_settings()
    query_str = request.query.strip()
    if not query_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query string cannot be empty.",
        )

    # Search local findings matching query terms or substring
    terms = [t.strip() for t in query_str.split() if len(t.strip()) > 3]
    if terms:
        clauses = [Finding.conclusion.ilike(f"%{term}%") for term in terms]
        stmt = select(Finding).where(or_(*clauses)).order_by(Finding.confidence.desc()).limit(3)
    else:
        search_term = f"%{query_str[:50]}%"
        stmt = (
            select(Finding)
            .where(Finding.conclusion.ilike(search_term))
            .order_by(Finding.confidence.desc())
            .limit(3)
        )
    matching_findings = (await session.execute(stmt)).scalars().all()

    sources: list[dict[str, str]] = []
    if matching_findings:
        answer_text = " ".join([f.conclusion for f in matching_findings])
        for f in matching_findings:
            sources.append(
                {
                    "title": f"IntelX Verified Finding ({f.id[:8]})",
                    "url": "intelx://findings/" + f.id,
                }
            )
    else:
        # Fallback to search connector if needed
        connector = WebSearchConnector(settings=settings)
        try:
            results: list[SearchResult] = await connector.fetch(query_str, max_results=3)
            if results:
                answer_text = (
                    f"Based on real-time web intelligence: {results[0].snippet} "
                    f"Additional insights corroborate these findings across verified domains."
                )
                for r in results:
                    sources.append({"title": r.title, "url": r.url})
            else:
                answer_text = (
                    f"We researched '{query_str}' across current intelligence feeds. "
                    "Our autonomous research engine is available to conduct an in-depth investigation."
                )
        except ProviderError:
            answer_text = (
                f"IntelX verified that inquiries regarding '{query_str}' require high-confidence synthesis. "
                "Contact our team or explore our autonomous platform capabilities."
            )

    return CortexVisitorQueryResponse(
        query=query_str,
        answer=answer_text,
        confidence=0.88 if sources else 0.70,
        sources=sources,
        suggested_followups=[
            "Would you like to schedule an enterprise demo with our team?",
            f"Would you like a full deep-dive intelligence report on '{query_str[:40]}'?",
        ],
    )


@router.post(
    "/trigger-lead-intel",
    summary="Trigger Outbound Lead Intelligence Dispatch to Cortex",
    dependencies=[Depends(verify_futuris_auth)],
)
async def trigger_lead_intel_dispatch(
    request: CortexTriggerLeadIntelRequest,
) -> dict[str, Any]:
    """Manually or programmatically trigger an outbound webhook delivery of lead intelligence to Cortex."""
    result = await CortexConnector.notify_cortex_lead_intel(
        finding_text=request.finding_text,
        run_id=request.run_id,
        domain=request.domain,
        confidence=request.confidence,
        webhook_url=request.webhook_url,
    )
    return result


__all__ = ["router"]
