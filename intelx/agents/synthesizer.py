"""INTELX Synthesizer Agent: Executive Intelligence Report Synthesis & Artifact Generation."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.agents.analyst import AnalysisResult
from intelx.agents.base import BaseAgent
from intelx.agents.critic import CritiqueReport
from intelx.core.confidence import get_confidence_label
from intelx.core.report import (
    filter_and_ground_findings,
    render_report_markdown,
    validate_citations,
)
from intelx.db.models import Claim, Evidence, Finding, ResearchRun, Source
from intelx.memory.artifacts import generate_and_save_artifacts
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class DraftFinding(BaseModel):
    """Draft finding proposition backed by claim IDs."""

    statement: str
    confidence: float = Field(default=0.80, ge=0.05, le=0.95)
    confidence_label: str = Field(default="High")
    claim_ids: list[str] = Field(default_factory=list)


# Alias for backward compatibility
SynthesizedFinding = DraftFinding


class DraftReport(BaseModel):
    """Structured LLM synthesis payload prior to markdown rendering."""

    executive_answer: str
    key_findings: list[DraftFinding] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class SynthesisResult(BaseModel):
    """Complete synthesized research outcome with rendered report and artifact records."""

    executive_summary: str
    findings: list[DraftFinding] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    report_markdown: str = ""
    overall_confidence_label: str = "Moderate"


class SynthesizerAgent(BaseAgent):
    """Agent producing final intelligence synthesis and creating artifacts."""

    SYSTEM_PROMPT = (
        "You are the INTELX Chief Intelligence Synthesizer.\n"
        "Your duty is to produce an authoritative, evidence-backed intelligence synthesis.\n"
        "Anchor every single finding to specific claim IDs from the provided evidence corpus.\n"
        "If evidence is insufficient to answer the objective, state this explicitly in the "
        "executive answer and detail exactly what data was missing in the gaps list."
    )

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        super().__init__(role="synthesizer", name="SynthesizerAgent", gateway=gateway)

    async def execute(
        self,
        objective: str,
        claims: list[Claim | dict[str, Any]],
        analysis: AnalysisResult | None = None,
        critique: CritiqueReport | dict[str, Any] | None = None,
        sources: list[Source] | None = None,
        evidence: list[Evidence] | None = None,
        degradations: list[str] | None = None,
        session: AsyncSession | None = None,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> SynthesisResult:
        """Synthesize verified claims into executive findings, render report, and emit artifacts."""
        all_sources = sources or []
        all_evidence = evidence or []

        if session and run_id:
            if not all_sources:
                stmt_s = select(Source).where(Source.created_by_run_id == run_id)
                run_sources = list((await session.execute(stmt_s)).scalars().all())

                claim_source_ids = [
                    getattr(c, "source_id", None)
                    or (c.get("source_id") if isinstance(c, dict) else None)
                    for c in claims
                ]
                claim_source_ids = [sid for sid in claim_source_ids if sid]
                if claim_source_ids:
                    stmt_cs = select(Source).where(Source.id.in_(claim_source_ids))
                    claim_sources = list((await session.execute(stmt_cs)).scalars().all())
                else:
                    claim_sources = []

                combined = {s.id: s for s in (run_sources + claim_sources)}
                all_sources = list(combined.values())

            if not all_evidence:
                stmt_e = select(Evidence).where(Evidence.created_by_run_id == run_id)
                all_evidence = list((await session.execute(stmt_e)).scalars().all())

        claims_by_id: dict[str, Any] = {}
        for c in claims:
            cid = getattr(c, "id", None) or (c.get("id") if isinstance(c, dict) else None)
            if cid:
                claims_by_id[cid] = c

        valid_source_ids = {
            getattr(s, "id", None) or (s.get("id") if isinstance(s, dict) else None)
            for s in all_sources
        }
        valid_source_ids = {sid for sid in valid_source_ids if sid}
        valid_claim_ids = set(claims_by_id.keys())

        # Insufficient evidence path
        if not claims:
            insufficient_finding = DraftFinding(
                statement=f"Insufficient evidence to answer objective: '{objective[:40]}'",
                confidence=0.10,
                confidence_label="Very low",
                claim_ids=[],
            )
            draft = DraftReport(
                executive_answer=(
                    f"Investigation for '{objective}' concluded with INSUFFICIENT EVIDENCE. "
                    "No verified empirical claims could be extracted within the designated scope."
                ),
                key_findings=[insufficient_finding],
                gaps=[
                    "No verifiable primary sources found matching scope constraints.",
                    "Sufficient evidence requires accessible authoritative disclosures.",
                ],
            )
            grounded_findings = []
            unverified_findings = [
                {
                    "conclusion": insufficient_finding.statement,
                    "confidence": 0.10,
                    "claim_ids_json": [],
                    "unverified_reason": "No primary evidence retrieved",
                }
            ]
            overall_conf_label = "Very low"
        else:
            # LLM Synthesis
            formatted_claims = []
            for c in claims:
                cid = getattr(c, "id", None) or c.get("id")
                ctext = getattr(c, "text", None) or c.get("text")
                cconf = getattr(c, "confidence", 1.0) or c.get("confidence", 1.0)
                formatted_claims.append({"id": cid, "text": ctext, "confidence": cconf})

            user_prompt = (
                f"RESEARCH OBJECTIVE: {objective}\n\n"
                f"VERIFIED EVIDENCE CLAIMS ({len(formatted_claims)} claims):\n"
                f"{json.dumps(formatted_claims, indent=2)}\n\n"
                "Produce the executive answer and key findings."
            )

            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            llm_res = await self.gateway.complete(
                messages=messages,
                role=self.role,
                schema_model=DraftReport,
                run_id=run_id,
            )
            draft: DraftReport = llm_res.parsed

            # Groundedness Check
            raw_findings = [f.model_dump() for f in draft.key_findings]
            grounded_findings, unverified_findings = filter_and_ground_findings(
                raw_findings, claims_by_id
            )

            # Overall confidence: max finding confidence that passed groundedness
            if grounded_findings:
                max_conf = max(f.get("confidence", 0.5) for f in grounded_findings)
                overall_conf_label = get_confidence_label(max_conf)
            else:
                overall_conf_label = "Low"

        # Render official report markdown
        critique_dict = critique.model_dump() if isinstance(critique, CritiqueReport) else critique
        report_md = render_report_markdown(
            objective=objective,
            executive_answer=draft.executive_answer,
            grounded_findings=grounded_findings,
            unverified_findings=unverified_findings,
            claims=claims,
            sources=all_sources,
            gaps=draft.gaps,
            critique=critique_dict,
            degradations=degradations,
            overall_confidence_label=overall_conf_label,
        )

        # CITATION INTEGRITY CHECK: Machine-enforced
        validate_citations(
            markdown_text=report_md,
            valid_source_ids=valid_source_ids,
            valid_claim_ids=valid_claim_ids,
        )

        # Persist findings to database
        if session and run_id:
            for gf in grounded_findings:
                finding_row = Finding(
                    run_id=run_id,
                    conclusion=gf.get("statement") or gf.get("conclusion") or "",
                    confidence=gf.get("confidence", 0.8),
                    confidence_method="v1-composite",
                    claim_ids_json=gf.get("claim_ids") or [],
                    gaps_json=[],
                    contradictions_json=[],
                    unverified_json=[],
                )
                session.add(finding_row)

            for uf in unverified_findings:
                finding_row = Finding(
                    run_id=run_id,
                    conclusion=uf.get("statement") or uf.get("conclusion") or "",
                    confidence=uf.get("confidence", 0.2),
                    confidence_method="v1-composite",
                    claim_ids_json=uf.get("claim_ids") or [],
                    gaps_json=draft.gaps,
                    contradictions_json=[],
                    unverified_json=[uf.get("unverified_reason", "Lacks grounded support")],
                )
                session.add(finding_row)

            await session.flush()

            # Generate and register all 4 artifacts
            stmt_r = select(ResearchRun).where(ResearchRun.id == run_id)
            run_obj = (await session.execute(stmt_r)).scalar_one_or_none()
            if run_obj:
                await generate_and_save_artifacts(
                    session=session,
                    run=run_obj,
                    report_markdown=report_md,
                    grounded_findings=grounded_findings,
                    unverified_findings=unverified_findings,
                    claims=claims,
                    sources=all_sources,
                    evidence_items=all_evidence,
                    gaps=draft.gaps,
                    degradations=degradations,
                    overall_confidence_label=overall_conf_label,
                )

        return SynthesisResult(
            executive_summary=draft.executive_answer,
            findings=draft.key_findings,
            gaps=draft.gaps,
            report_markdown=report_md,
            overall_confidence_label=overall_conf_label,
        )
