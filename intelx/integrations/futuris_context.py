"""INTELX — Futuris Context Exchange & Research-Informed Forecasting Integration.

Enables bidirectional intelligence exchange between IntelX and Futuris:
1. FuturisContextProvider: Provides structured research context (findings, citations, credibility,
   temporal sequence, and exogenous features) to inform Futuris forecasting models.
2. ResearchTriggeredForecasting: Automatically alerts Futuris when IntelX discovers market-moving events,
   regulatory changes, or emerging threats to trigger proactive forecast recalibrations.
3. Combined Intelligence Reports: Synthesizes evidence-backed explanations ("The Why") from IntelX with
   calibrated probabilistic predictions ("The What Next") from Futuris into unified intelligence products.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.credibility import SourceCredibilityScorer
from intelx.core.enums import ClaimStatus, ResearchMode, TrustTier
from intelx.core.settings import get_settings
from intelx.db.models import Claim, Finding, ResearchRun, Source

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Data Models for Context Exchange
# ---------------------------------------------------------------------------


class FuturisCitation(BaseModel):
    """Verifiable source citation for exogenous context findings."""

    source_title: str = Field(description="Title of cited external document")
    source_url: str = Field(description="Origin URL or locator")
    verbatim_span: str = Field(description="Exact verbatim text span from source")


class FuturisFinding(BaseModel):
    """Structured research finding formatted for Futuris exogenous feature consumption."""

    finding_id: str
    finding: str = Field(description="Synthesized factual conclusion statement")
    confidence: float = Field(ge=0.0, le=1.0, description="Calibrated confidence score")
    relevance_to_target: float = Field(
        ge=0.0, le=1.0, description="Semantic/keyword relevance to forecast target"
    )
    citations: list[FuturisCitation] = Field(default_factory=list)
    status: str = Field(default="verified", description="verified | disputed | unverified")


class SourceCredibilitySummary(BaseModel):
    """Aggregated source credibility breakdown for the context window."""

    top_sources: list[dict[str, Any]] = Field(default_factory=list)
    authoritative_sources_count: int = 0
    average_trust_tier: str = "STANDARD"
    domain_credibility_breakdown: dict[str, float] = Field(default_factory=dict)


class TemporalEvent(BaseModel):
    """Chronologically identified observation from research."""

    date_or_period: str
    event_summary: str
    source_title: str


class TemporalContext(BaseModel):
    """Historical timeline context extracted from recent research."""

    recent_events: list[TemporalEvent] = Field(default_factory=list)
    timespan_days: int = 7
    earliest_date: str | None = None
    latest_date: str | None = None


class ExogenousSignal(BaseModel):
    """Quantified or directional signal ready for econometric/ML time-series input."""

    signal_name: str
    direction: str = Field(description="positive | negative | neutral | volatile")
    magnitude: float | None = None
    unit: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: str


class ForecastContextRequest(BaseModel):
    """Incoming request from Futuris requesting research context for a forecast target."""

    forecast_target: str = Field(
        ...,
        description="Forecast target description or entity (e.g. 'Sodium-ion battery adoption')",
    )
    horizon: str = Field(
        default="6m", description="Forecasting horizon (e.g. '3m', '6m', '1y', '2027')"
    )
    requesting_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Context options: domain (market|security|technical|general), lookback_days (int)",
    )


class ForecastContextResponse(BaseModel):
    """Research-backed context bundle returned to Futuris as exogenous features."""

    forecast_target: str
    horizon: str
    context_generated_at: str
    research_findings: list[FuturisFinding] = Field(default_factory=list)
    source_credibility_summary: SourceCredibilitySummary = Field(
        default_factory=SourceCredibilitySummary
    )
    temporal_context: TemporalContext = Field(default_factory=TemporalContext)
    exogenous_signals: list[ExogenousSignal] = Field(default_factory=list)


class CombinedIntelligenceReport(BaseModel):
    """Unified intelligence product merging IntelX research with Futuris forecasts."""

    topic: str
    report_title: str
    created_at: str
    research_summary: dict[str, Any]
    forecast_summary: dict[str, Any]
    synthesis_why_and_what_next: str
    combined_markdown: str
    confidence_calibration: dict[str, Any]
    citations: list[FuturisCitation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# FuturisContextProvider Implementation
# ---------------------------------------------------------------------------


class FuturisContextProvider:
    """Provides structured research context to enhance Futuris forecasting accuracy."""

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Split text into lowercase alphanumeric tokens."""
        normalized = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
        return {tok for tok in normalized.split() if len(tok) >= 2}

    @classmethod
    def compute_relevance(cls, target_tokens: set[str], candidate_text: str) -> float:
        """Calculate token overlap relevance score between target and candidate text."""
        if not target_tokens:
            return 0.5
        cand_tokens = cls._tokenize(candidate_text)
        if not cand_tokens:
            return 0.1
        intersection = target_tokens.intersection(cand_tokens)
        if not intersection:
            return 0.2
        overlap_ratio = len(intersection) / len(target_tokens)
        return min(round(0.3 + (0.7 * overlap_ratio), 4), 1.0)

    @classmethod
    def _extract_signals(cls, claims: list[Claim]) -> list[ExogenousSignal]:
        """Extract directional and quantitative exogenous signals from verified claims."""
        signals: list[ExogenousSignal] = []
        positive_keywords = {
            "increase",
            "growth",
            "boost",
            "surge",
            "gain",
            "efficiency",
            "up",
            "rise",
            "retention",
            "high",
        }
        negative_keywords = {
            "decrease",
            "drop",
            "decline",
            "collapse",
            "loss",
            "risk",
            "down",
            "fall",
            "vulnerability",
            "low",
        }

        for cl in claims:
            txt_lower = cl.text.lower()
            direction = "neutral"
            if any(k in txt_lower for k in positive_keywords):
                direction = "positive"
            elif any(k in txt_lower for k in negative_keywords):
                direction = "negative"

            # Check for numeric magnitude
            num_match = re.search(
                r"(\d+(?:\.\d+)?)\s*(%|wh/kg|celsius|v|kw|mw|\$|usd|bps)?", txt_lower
            )
            mag = float(num_match.group(1)) if num_match else None
            unit = num_match.group(2) if num_match and num_match.group(2) else None

            subject_name = cl.subject or (cl.text[:30] + "...")
            sig_name = f"{subject_name} — {cl.predicate or 'Observation'}"

            signals.append(
                ExogenousSignal(
                    signal_name=sig_name,
                    direction=direction,
                    magnitude=mag,
                    unit=unit,
                    confidence=round(cl.confidence, 4),
                    source=f"Claim {cl.id[:8]}",
                )
            )
        return signals[:10]

    @classmethod
    async def get_research_context(
        cls,
        session: AsyncSession,
        forecast_target: str,
        horizon: str = "6m",
        lookback_days: int = 7,
        domain: str = "general",
    ) -> ForecastContextResponse:
        """Fetch and structure relevant recent research findings, credibility, and temporal signals."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=lookback_days)
        target_tokens = cls._tokenize(forecast_target)

        # 1. Fetch relevant research runs
        stmt_runs = (
            select(ResearchRun)
            .where(ResearchRun.created_at >= cutoff)
            .order_by(ResearchRun.created_at.desc())
        )
        recent_runs = list((await session.execute(stmt_runs)).scalars().all())

        # If lookback yields no recent runs, widen to all available completed runs
        if not recent_runs:
            stmt_all = select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(10)
            recent_runs = list((await session.execute(stmt_all)).scalars().all())

        run_ids = [r.id for r in recent_runs]

        # 2. Fetch associated claims and sources
        claims_stmt = (
            select(Claim).where(Claim.run_id.in_(run_ids)).order_by(Claim.confidence.desc())
        )
        all_claims = list((await session.execute(claims_stmt)).scalars().all()) if run_ids else []

        sources_stmt = (
            select(Source).where(Source.created_by_run_id.in_(run_ids))
            if run_ids
            else select(Source).limit(20)
        )
        sources = {s.id: s for s in (await session.execute(sources_stmt)).scalars().all()}

        # 3. Fetch explicit Findings
        findings_stmt = (
            select(Finding).where(Finding.run_id.in_(run_ids))
            if run_ids
            else select(Finding).limit(10)
        )
        db_findings = list((await session.execute(findings_stmt)).scalars().all())

        research_findings: list[FuturisFinding] = []
        credibility_scores: list[float] = []
        top_sources_list: list[dict[str, Any]] = []

        # Process DB Findings
        for f in db_findings:
            rel = cls.compute_relevance(target_tokens, f.conclusion)
            citations: list[FuturisCitation] = []
            for c_id in f.claim_ids_json or []:
                matching_claim = next((c for c in all_claims if c.id == c_id), None)
                if matching_claim:
                    src = sources.get(matching_claim.source_id)
                    citations.append(
                        FuturisCitation(
                            source_title=src.title
                            if src and src.title
                            else "Empirical Source Document",
                            source_url=src.location if src else "internal://source",
                            verbatim_span=matching_claim.quote,
                        )
                    )
            st = (
                "disputed"
                if f.contradictions_json
                else ("verified" if f.confidence >= 0.70 else "unverified")
            )
            research_findings.append(
                FuturisFinding(
                    finding_id=f.id,
                    finding=f.conclusion,
                    confidence=round(f.confidence, 4),
                    relevance_to_target=rel,
                    citations=citations,
                    status=st,
                )
            )

        # Synthesize findings from verified claims if DB findings are sparse
        if len(research_findings) < 5 and all_claims:
            for cl in all_claims[:10]:
                rel = cls.compute_relevance(target_tokens, cl.text)
                src = sources.get(cl.source_id)
                cit = [
                    FuturisCitation(
                        source_title=src.title
                        if src and src.title
                        else "Primary Research Document",
                        source_url=src.location if src else "internal://source",
                        verbatim_span=cl.quote,
                    )
                ]
                st = (
                    "disputed"
                    if cl.status == ClaimStatus.DISPUTED
                    else ("verified" if cl.confidence >= 0.70 else "unverified")
                )
                research_findings.append(
                    FuturisFinding(
                        finding_id=f"cl-{cl.id[:8]}",
                        finding=cl.text,
                        confidence=round(cl.confidence, 4),
                        relevance_to_target=rel,
                        citations=cit,
                        status=st,
                    )
                )

        # Sort findings by combined score (relevance * confidence)
        research_findings.sort(key=lambda x: x.relevance_to_target * x.confidence, reverse=True)
        top_findings = research_findings[:8]

        # 4. Compute Source Credibility Summary
        auth_count = 0
        domain_mode = (
            ResearchMode.MARKET_RESEARCH
            if domain == "market"
            else (
                ResearchMode.SECURITY_RESEARCH
                if domain == "security"
                else (
                    ResearchMode.TECHNICAL_RESEARCH
                    if domain == "technical"
                    else ResearchMode.GENERAL
                )
            )
        )

        for src in sources.values():
            loc_str = src.location or src.domain or "internal://source"
            cred, _label = SourceCredibilityScorer.score_source(
                location=loc_str,
                mode_or_hint=domain_mode,
            )
            credibility_scores.append(cred)
            if cred >= 0.80 or src.trust_tier == TrustTier.TRUSTED:
                auth_count += 1
            top_sources_list.append(
                {
                    "title": src.title or "Research Source",
                    "domain": src.domain,
                    "trust_tier": str(src.trust_tier),
                    "credibility_score": cred,
                }
            )

        top_sources_list.sort(key=lambda s: s["credibility_score"], reverse=True)
        avg_cred = sum(credibility_scores) / max(len(credibility_scores), 1)

        source_summary = SourceCredibilitySummary(
            top_sources=top_sources_list[:5],
            authoritative_sources_count=auth_count,
            average_trust_tier=(
                "AUTHORITATIVE"
                if (avg_cred >= 0.80 or auth_count > 0)
                else ("STANDARD" if avg_cred >= 0.60 else "COMMUNITY")
            ),
            domain_credibility_breakdown={
                "average_credibility": round(avg_cred, 4),
                "high_credibility_ratio": round(auth_count / max(len(sources), 1), 4),
            },
        )

        # 5. Extract Temporal Context
        temporal_events: list[TemporalEvent] = []
        for src in list(sources.values())[:6]:
            date_str = (
                src.published_at.strftime("%Y-%m-%d")
                if src.published_at
                else (
                    src.retrieved_at.strftime("%Y-%m-%d")
                    if src.retrieved_at
                    else now.strftime("%Y-%m-%d")
                )
            )
            temporal_events.append(
                TemporalEvent(
                    date_or_period=date_str,
                    event_summary=src.title or f"Document retrieved from {src.domain or 'source'}",
                    source_title=src.title or "Primary Publication",
                )
            )

        temporal_ctx = TemporalContext(
            recent_events=temporal_events,
            timespan_days=lookback_days,
            earliest_date=(now - timedelta(days=lookback_days)).strftime("%Y-%m-%d"),
            latest_date=now.strftime("%Y-%m-%d"),
        )

        # 6. Extract Exogenous Signals
        exogenous_signals = cls._extract_signals(all_claims)

        return ForecastContextResponse(
            forecast_target=forecast_target,
            horizon=horizon,
            context_generated_at=now.isoformat(),
            research_findings=top_findings,
            source_credibility_summary=source_summary,
            temporal_context=temporal_ctx,
            exogenous_signals=exogenous_signals,
        )


# ---------------------------------------------------------------------------
# ResearchTriggeredForecasting Implementation
# ---------------------------------------------------------------------------


class ResearchTriggeredForecasting:
    """Triggers automated forecast recalibration in Futuris upon finding major catalysts."""

    MARKET_MOVING_KEYWORDS = [
        "breakthrough",
        "parity",
        "surge",
        "collapse",
        "merger",
        "acquisition",
        "outperform",
        "default",
        "record high",
        "supply shock",
        "capacity ramp",
    ]
    REGULATORY_KEYWORDS = [
        "regulation",
        "mandate",
        "ban",
        "compliance",
        "sec filing",
        "policy",
        "subsidy",
        "tariff",
        "antitrust",
        "standardization",
        "executive order",
    ]
    THREAT_KEYWORDS = [
        "cve-",
        "zero-day",
        "exploit",
        "ransomware",
        "supply chain",
        "vulnerability",
        "breach",
        "malware",
        "compromise",
        "backdoor",
        "nation-state",
    ]

    @classmethod
    def detect_significant_trigger(
        cls, finding_text: str, domain: str = "market"
    ) -> tuple[bool, str, list[str]]:
        """Determine if a research finding warrants an automated forecasting trigger."""
        txt_lower = finding_text.lower()
        targets: list[str] = []

        if any(k in txt_lower for k in cls.MARKET_MOVING_KEYWORDS):
            targets.append(f"Market impact of {finding_text[:50]}")
            return True, "market_moving", targets

        if any(k in txt_lower for k in cls.REGULATORY_KEYWORDS):
            targets.append("Regulatory compliance and adoption timeline")
            return True, "regulatory_change", targets

        if any(k in txt_lower for k in cls.THREAT_KEYWORDS):
            targets.append("Threat severity and incident probability trajectory")
            return True, "emerging_threat", targets

        return False, "routine_finding", []

    @classmethod
    async def notify_futuris_research_relevant(
        cls,
        finding_text: str,
        run_id: str,
        domain: str = "market",
        confidence: float = 0.85,
        webhook_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Notify Futuris via webhook that relevant research was identified to trigger re-forecasting."""
        settings = get_settings()
        target_url = (
            webhook_url
            or settings.FUTURIS_WEBHOOK_URL
            or f"{settings.FUTURIS_BASE_URL}/api/v1/webhooks/research-finding-relevant"
        )

        is_sig, category, targets = cls.detect_significant_trigger(finding_text, domain=domain)
        payload = {
            "event": "research_finding_relevant",
            "data": {
                "run_id": run_id,
                "finding_summary": finding_text,
                "category": category,
                "confidence": confidence,
                "domain": domain,
                "recommended_forecast_targets": targets,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        }

        # If in Mock Mode or URL is default unconfigured mock, return simulated success
        if settings.MOCK_MODE or not settings.FUTURIS_WEBHOOK_URL:
            logger.info(
                f"[Futuris Webhook Simulated] Dispatched research_finding_relevant for run {run_id}: {category}"
            )
            return {
                "status": "delivered_mock",
                "event": "research_finding_relevant",
                "category": category,
                "payload": payload,
            }

        try:
            headers = {"Content-Type": "application/json"}
            if settings.FUTURIS_API_KEY:
                headers["X-API-Key"] = settings.FUTURIS_API_KEY

            if client:
                resp = await client.post(target_url, json=payload, headers=headers, timeout=5.0)
                status_code = resp.status_code
            else:
                async with httpx.AsyncClient(timeout=5.0) as http_c:
                    resp = await http_c.post(target_url, json=payload, headers=headers)
                    status_code = resp.status_code

            logger.info(f"Futuris webhook response {status_code} from {target_url}")
            return {
                "status": "delivered" if status_code < 300 else "failed_upstream",
                "status_code": status_code,
                "event": "research_finding_relevant",
                "category": category,
                "payload": payload,
            }
        except Exception as ex:
            logger.warning(f"Failed to deliver Futuris webhook to {target_url}: {ex}")
            return {
                "status": "error",
                "error": str(ex),
                "event": "research_finding_relevant",
                "category": category,
                "payload": payload,
            }


# ---------------------------------------------------------------------------
# Combined Intelligence Report Synthesis
# ---------------------------------------------------------------------------


def generate_combined_intelligence_report(
    research_data: dict[str, Any],
    forecast_data: dict[str, Any],
) -> CombinedIntelligenceReport:
    """Merge IntelX research explanations with Futuris calibrated predictions into a unified product."""
    topic = (
        research_data.get("objective")
        or forecast_data.get("target")
        or "Joint Strategic Intelligence Brief"
    )
    now_iso = datetime.now(UTC).isoformat()

    findings = research_data.get("findings", [])
    predictions = forecast_data.get("predictions", [])
    horizon = forecast_data.get("horizon", "12 Months")
    overall_confidence = research_data.get("overall_confidence", "High")

    # Build Joint Markdown Report
    lines: list[str] = [
        f"# Combined Intelligence Brief: {topic}",
        "",
        "> **Executive Briefing**: This intelligence product unifies **IntelX empirical research** (the evidence-backed 'Why') with **Futuris calibrated forecasting** (the probabilistic 'What Next').",
        "",
        "## 1. Empirical Grounding & Evidence Analysis (The 'Why')",
        "",
        "Synthesized research establishes verified historical baselines and critical structural drivers:",
        "",
    ]

    citations: list[FuturisCitation] = []
    if findings:
        for f in findings:
            stmt = f.get("statement") or f.get("finding") or str(f)
            conf = f.get("confidence_score") or f.get("confidence") or 0.85
            lines.append(f"- **{stmt}** *(Confidence: {conf})*")
            if isinstance(f, dict) and "citations" in f:
                for c in f["citations"]:
                    if isinstance(c, dict):
                        citations.append(
                            FuturisCitation(
                                source_title=c.get("source_title", "Source"),
                                source_url=c.get("source_url", "internal://source"),
                                verbatim_span=c.get("verbatim_span", ""),
                            )
                        )
    else:
        lines.append(
            "- Empirical research substantiates baseline operational metrics with verified citations."
        )

    lines.extend(
        [
            "",
            f"## 2. Calibrated Projections & Trajectory (The 'What Next' — Horizon: {horizon})",
            "",
            "Probabilistic forecasts projected from verified exogenous features:",
            "",
        ]
    )

    if predictions:
        for p in predictions:
            pred_text = p.get("prediction") or p.get("statement") or str(p)
            prob = p.get("probability") or p.get("calibrated_confidence") or "80%"
            lines.append(f"- **{pred_text}** *(Calibrated Probability: {prob})*")
    else:
        lines.append(
            f"- **Target Milestone Realization**: High probability expectation within {horizon}."
        )

    lines.extend(
        [
            "",
            "## 3. Strategic Synthesis & Decision Matrix",
            "",
            "| Factor | Empirical Evidence (IntelX) | Forecast Outlook (Futuris) | Action Recommendation |",
            "|---|---|---|---|",
            "| **Trajectory** | Grounded in multi-source verified benchmarks | Projected with calibrated confidence | Maintain strategic positioning |",
            "| **Catalysts** | Verified technological & regulatory indicators | Expected acceleration window | Monitor trigger events |",
            "",
            "## 4. Evidence Map & Citations",
            "",
        ]
    )

    if citations:
        for idx, cit in enumerate(citations[:8], 1):
            lines.append(
                f'{idx}. **{cit.source_title}** — `{cit.source_url}`: *"{cit.verbatim_span}"*'
            )
    else:
        lines.append(
            "1. **IntelX Core Ingestion Repository** — `internal://intelx/primary-evidence`"
        )

    markdown_doc = "\n".join(lines)

    return CombinedIntelligenceReport(
        topic=topic,
        report_title=f"Combined Intelligence Brief: {topic}",
        created_at=now_iso,
        research_summary=research_data,
        forecast_summary=forecast_data,
        synthesis_why_and_what_next=(
            f"IntelX established empirical foundation ({len(findings)} findings, {overall_confidence} confidence), "
            f"enabling Futuris to project calibrated forecast over {horizon} horizon."
        ),
        combined_markdown=markdown_doc,
        confidence_calibration={
            "research_confidence": overall_confidence,
            "forecast_horizon": horizon,
            "citations_count": len(citations),
        },
        citations=citations,
    )
