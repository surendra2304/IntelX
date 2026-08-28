"""INTELX Synthesizer Agent: Executive Summary and Evidence-Backed Finding Formulation."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.agents.analyst import AnalysisResult
from intelx.agents.base import BaseAgent
from intelx.db.models import Claim, Finding
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class SynthesizedFinding(BaseModel):
    """Structured research conclusion backed by specific claim IDs."""

    conclusion: str
    confidence: float = Field(default=0.80, ge=0.05, le=0.95)
    confidence_label: str = Field(default="High")
    claim_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    unverified: list[str] = Field(default_factory=list)


class SynthesisResult(BaseModel):
    """Complete research synthesis payload."""

    executive_summary: str
    findings: list[SynthesizedFinding] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class SynthesizerAgent(BaseAgent):
    """Agent producing final executive intelligence report and persistent findings."""

    SYSTEM_PROMPT = (
        "You are the INTELX Chief Intelligence Synthesizer.\n"
        "Your duty is to produce an authoritative, evidence-backed intelligence synthesis.\n"
        "Anchor every single finding to specific claim IDs from the provided evidence corpus.\n"
        "If evidence is insufficient to answer the objective, state this explicitly in the "
        "executive summary and detail exactly what data was missing in the gaps list."
    )

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        super().__init__(role="synthesizer", name="SynthesizerAgent", gateway=gateway)

    async def execute(
        self,
        objective: str,
        claims: list[Claim | dict[str, Any]],
        analysis: AnalysisResult | None = None,
        session: AsyncSession | None = None,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> SynthesisResult:
        """Synthesize verified claims into executive findings and persist to database."""
        if not claims:
            # Insufficient evidence path
            insufficient_finding = SynthesizedFinding(
                conclusion=f"Insufficient evidence for objective: '{objective[:40]}'",
                confidence=0.10,
                confidence_label="Very low",
                claim_ids=[],
                gaps=[
                    "No verifiable primary sources found matching scope constraints.",
                    "Sufficient evidence requires accessible authoritative disclosures.",
                ],
                contradictions=[],
                unverified=[],
            )
            result = SynthesisResult(
                executive_summary=(
                    f"Investigation for '{objective}' concluded with INSUFFICIENT EVIDENCE. "
                    "No verified empirical claims could be extracted within the designated scope."
                ),
                findings=[insufficient_finding],
                gaps=insufficient_finding.gaps,
            )

            if session and run_id:
                finding_row = Finding(
                    run_id=run_id,
                    conclusion=insufficient_finding.conclusion,
                    confidence=insufficient_finding.confidence,
                    confidence_method="v1-composite",
                    claim_ids_json=[],
                    gaps_json=insufficient_finding.gaps,
                    contradictions_json=[],
                    unverified_json=[],
                )
                session.add(finding_row)
                await session.flush()

            return result

        # Standard synthesis path
        formatted_claims = []
        for c in claims:
            if isinstance(c, dict):
                formatted_claims.append(
                    {"id": c.get("id"), "text": c.get("text"), "confidence": c.get("confidence")}
                )
            else:
                formatted_claims.append({"id": c.id, "text": c.text, "confidence": c.confidence})

        user_prompt = (
            f"RESEARCH OBJECTIVE: {objective}\n\n"
            f"VERIFIED EVIDENCE CLAIMS ({len(formatted_claims)} claims):\n"
            f"{json.dumps(formatted_claims, indent=2)}\n\n"
            "Produce the final executive summary and structured findings."
        )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        llm_res = await self.gateway.complete(
            messages=messages,
            role=self.role,
            schema_model=SynthesisResult,
            run_id=run_id,
        )

        synthesis: SynthesisResult = llm_res.parsed

        # Persist findings to database
        if session and run_id:
            for f in synthesis.findings:
                finding_row = Finding(
                    run_id=run_id,
                    conclusion=f.conclusion,
                    confidence=f.confidence,
                    confidence_method="v1-composite",
                    claim_ids_json=f.claim_ids,
                    gaps_json=f.gaps,
                    contradictions_json=f.contradictions,
                    unverified_json=f.unverified,
                )
                session.add(finding_row)
            await session.flush()

        return synthesis
