"""INTELX — StrateX Algorithmic Trading Intelligence API Router.

Provides real-time research synthesis, sentiment drivers, regulatory indicators,
and volatility impact factors directly consumable by StrateX trading bots and advisory telemetry.
"""

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.api.v1.futuris import verify_futuris_auth
from intelx.connectors.search import SearchResult, WebSearchConnector
from intelx.core.enums import RunOutcome, RunStatus
from intelx.core.errors import ProviderError
from intelx.core.settings import get_settings
from intelx.db.models import Claim, Finding, ResearchRun
from intelx.db.session import get_db_session
from intelx.integrations.stratex_context import StratexConnector

logger = logging.getLogger("intelx.api.v1.stratex")

router = APIRouter(tags=["StrateX Algorithmic Trading Integration"])


class StratexResearchRequest(BaseModel):
    """Payload sent by StrateX IntelXMarketClient when triggering market research."""

    symbol: str = Field(..., description="Asset or pair symbol, e.g. BTC, ETH, SOL, BTCUSDT")
    query: str | None = Field(
        None,
        description="Hypothesis or query to investigate (defaults to volatility/macro inquiry)",
    )
    trigger_reason: str = Field(
        default="MANUAL_OR_EVENT",
        description="Reason trigger: VOLATILITY_2_SIGMA | LOW_ADVISORY_CONFIDENCE | DRAWDOWN_THRESHOLD | MANUAL_OR_EVENT",
    )


class StratexResearchResponse(BaseModel):
    """Structured research report consumed by StrateX for automated execution and advisory."""

    symbol: str
    trigger_reason: str
    query: str
    summary: str
    findings: dict[str, Any]
    sentiment_drivers: list[str]
    regulatory_changes: list[str]
    macro_events: list[str]
    sentiment_score: float = Field(
        default=0.0, ge=-1.0, le=1.0, description="Directional sentiment score (-1.0 to 1.0)"
    )
    volatility_impact_factor: float = Field(
        default=1.0, ge=0.1, le=5.0, description="Expected volatility multiplier (baseline 1.0)"
    )
    timestamp: float = Field(default_factory=time.time)
    expires_at: float = Field(default_factory=lambda: time.time() + 1800)


class StratexSignalTriggerRequest(BaseModel):
    """Payload to trigger an outbound trade signal dispatch to StrateX."""

    finding_text: str = Field(..., description="Key catalyst or market finding")
    run_id: str = Field(..., description="IntelX research run ID")
    domain: str = Field(default="market")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    webhook_url: str | None = None


def _clean_symbol(raw_symbol: str) -> str:
    """Normalize raw trading pair to base asset ticker, e.g. BTCUSDT -> BTC."""
    s = raw_symbol.upper().strip()
    for suffix in ("USDT", "BUSD", "USDC", "USD", "EUR", "PERP"):
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[: -len(suffix)]
    return s


@router.post(
    "/intelligence/research",
    response_model=StratexResearchResponse,
    summary="Generate Market Research for StrateX Asset",
    dependencies=[Depends(verify_futuris_auth)],
)
async def query_stratex_market_research(
    req: StratexResearchRequest,
    session: AsyncSession = Depends(get_db_session),
) -> StratexResearchResponse:
    """Provide real-time evidence-backed intelligence on market volatility, catalysts, and macro factors."""
    symbol = req.symbol.strip()
    clean_sym = _clean_symbol(symbol)
    trigger_reason = req.trigger_reason
    query = (
        req.query
        or f"What events are driving {symbol} volatility? Regulatory changes? Institutional flows? Macro events?"
    )

    now_ts = time.time()
    expires_at = now_ts + 1800.0

    # 1. Search local IntelX DB for recent completed runs, findings, or claims matching symbol
    search_token = f"%{clean_sym}%"
    stmt_runs = (
        select(ResearchRun)
        .where(
            ResearchRun.objective.ilike(search_token),
            ResearchRun.status == RunStatus.COMPLETED,
            ResearchRun.outcome == RunOutcome.ANSWERED,
        )
        .order_by(ResearchRun.created_at.desc())
        .limit(5)
    )
    matching_runs = list((await session.execute(stmt_runs)).scalars().all())

    db_findings_text: list[str] = []
    if matching_runs:
        run_ids = [r.id for r in matching_runs]
        f_stmt = select(Finding).where(Finding.run_id.in_(run_ids)).limit(10)
        found_objs = list((await session.execute(f_stmt)).scalars().all())
        db_findings_text = [f.conclusion for f in found_objs if f.conclusion]

        if not db_findings_text:
            c_stmt = select(Claim).where(Claim.run_id.in_(run_ids)).limit(10)
            claims_objs = list((await session.execute(c_stmt)).scalars().all())
            db_findings_text = [c.text for c in claims_objs if c.text]

    # 2. If DB has matching findings, structure them into StrateX categories
    sentiment_drivers: list[str] = []
    regulatory_changes: list[str] = []
    macro_events: list[str] = []

    pos_kw = {"surge", "bullish", "rally", "inflow", "gain", "breakout", "accumulate", "boost"}
    neg_kw = {"drop", "bearish", "plummet", "outflow", "loss", "decline", "selloff", "crash"}
    reg_kw = {
        "sec",
        "cftc",
        "regulation",
        "etf",
        "approval",
        "compliance",
        "lawsuit",
        "ban",
        "court",
        "legal",
    }
    macro_kw = {
        "fomc",
        "fed",
        "interest rate",
        "inflation",
        "cpi",
        "liquidity",
        "yield",
        "dollar",
        "treasury",
    }

    pos_count = 0
    neg_count = 0

    for text in db_findings_text:
        txt_lower = text.lower()
        if any(k in txt_lower for k in pos_kw):
            pos_count += 1
            sentiment_drivers.append(text[:120])
        elif any(k in txt_lower for k in neg_kw):
            neg_count += 1
            sentiment_drivers.append(text[:120])

        if any(k in txt_lower for k in reg_kw):
            regulatory_changes.append(text[:120])
        if any(k in txt_lower for k in macro_kw):
            macro_events.append(text[:120])

    # 3. Always request current news; stored findings supplement, but do not replace,
    # a live source check. Never fill gaps with generic placeholder statements.
    news_results: list[SearchResult] = []
    search_attempted = True
    search_failed = False
    try:
        connector = WebSearchConnector(settings=get_settings())
        news_results = await connector.fetch(query, max_results=6)
    except ProviderError as exc:
        search_failed = True
        logger.warning("Live search enrichment failed for %s (%s)", symbol, type(exc).__name__)
        if not db_findings_text:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Market news providers are unavailable; no evidence-backed report can be generated.",
            ) from exc

    for res in news_results:
        title = res.title or res.snippet
        txt_lower = f"{title} {res.snippet}".lower()
        if any(k in txt_lower for k in reg_kw) and len(regulatory_changes) < 3:
            regulatory_changes.append(title[:120])
        if any(k in txt_lower for k in macro_kw) and len(macro_events) < 3:
            macro_events.append(title[:120])
        if any(k in txt_lower for k in pos_kw | neg_kw) and len(sentiment_drivers) < 4:
            sentiment_drivers.append(title[:120])

        if any(k in txt_lower for k in pos_kw):
            pos_count += 1
        elif any(k in txt_lower for k in neg_kw):
            neg_count += 1

    evidence_sources = [
        {"kind": "intelx_finding_or_claim", "text": text} for text in db_findings_text
    ]
    evidence_sources.extend(
        {
            "kind": "news_search",
            "title": result.title,
            "url": result.url,
            "snippet": result.snippet,
        }
        for result in news_results
    )
    evidence_count = len(evidence_sources)

    # Calculate sentiment score (-1.0 to +1.0); no directional signal is neutral.
    total_sentiment_signals = pos_count + neg_count
    if total_sentiment_signals > 0:
        raw_score = (pos_count - neg_count) / total_sentiment_signals
        sentiment_score = round(max(-1.0, min(1.0, raw_score * 0.8)), 2)
    else:
        sentiment_score = 0.0

    # Keep the volatility factor at its neutral baseline without source evidence.
    vol_impact = 1.0
    if evidence_count and "VOLATILITY" in trigger_reason:
        vol_impact = 1.45
    elif evidence_count and "DRAWDOWN" in trigger_reason:
        vol_impact = 1.30
    elif evidence_count and "LOW_ADVISORY" in trigger_reason:
        vol_impact = 1.20

    if evidence_count == 0:
        summary = (
            f"No verified market evidence is available for {symbol}; "
            "no directional sentiment or volatility assessment was produced."
        )
    elif not (sentiment_drivers or regulatory_changes or macro_events):
        summary = (
            f"Retrieved {evidence_count} source record(s) for {symbol}, but none supported a "
            "classified sentiment, regulatory, or macro indicator; no directional assessment was produced."
        )
    else:
        summary = (
            f"IntelX evidence-backed market intelligence for {symbol} (trigger: {trigger_reason}): "
            f"Sentiment bias is {sentiment_score:+.2f} with volatility factor {vol_impact:.2f}x. "
            f"Identified {len(sentiment_drivers)} sentiment drivers, {len(regulatory_changes)} regulatory factors, "
            f"and {len(macro_events)} macro indicators from {evidence_count} source record(s)."
        )

    findings_status = (
        "INSUFFICIENT_EVIDENCE"
        if evidence_count == 0
        else ("PARTIAL_EVIDENCE" if search_failed else "EVIDENCE_AVAILABLE")
    )
    findings_payload = {
        "status": findings_status,
        "symbol": symbol,
        "base_asset": clean_sym,
        "sentiment_score": sentiment_score,
        "volatility_impact_factor": vol_impact,
        "sentiment_drivers": sentiment_drivers,
        "regulatory_changes": regulatory_changes,
        "macro_events": macro_events,
        "sources_count": evidence_count,
        "evidence_sources": evidence_sources,
        "external_search_status": (
            "failed" if search_failed else ("completed" if search_attempted else "not_needed")
        ),
    }

    return StratexResearchResponse(
        symbol=symbol,
        trigger_reason=trigger_reason,
        query=query,
        summary=summary,
        findings=findings_payload,
        sentiment_drivers=sentiment_drivers,
        regulatory_changes=regulatory_changes,
        macro_events=macro_events,
        sentiment_score=sentiment_score,
        volatility_impact_factor=vol_impact,
        timestamp=now_ts,
        expires_at=expires_at,
    )


@router.post(
    "/stratex/trigger-signal",
    summary="Dispatch Research Trade Signal to StrateX",
    dependencies=[Depends(verify_futuris_auth)],
)
async def trigger_stratex_signal(
    req: StratexSignalTriggerRequest,
) -> dict[str, Any]:
    """Manually or programmatically notify StrateX of an actionable research finding."""
    result = await StratexConnector.notify_stratex_trade_signal(
        finding_text=req.finding_text,
        run_id=req.run_id,
        domain=req.domain,
        confidence=req.confidence,
        webhook_url=req.webhook_url,
    )
    return result
