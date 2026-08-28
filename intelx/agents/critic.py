"""INTELX Critic Agent: Adversarial Self-Critique, Overconfidence Detection, and Gap Analysis."""

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from intelx.agents.base import BaseAgent
from intelx.db.models import Claim
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class OverconfidentClaim(BaseModel):
    """Claim flagged for having confidence ratings unaligned with underlying evidence."""

    claim_id: str
    reason: str


class CritiqueReport(BaseModel):
    """Adversarial critique assessment of findings and evidence sufficiency."""

    unsupported_conclusions: list[str] = Field(default_factory=list)
    overconfident_claims: list[OverconfidentClaim] = Field(default_factory=list)
    missing_angles: list[str] = Field(default_factory=list)
    severity: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    summary: str = Field(default="Analysis is grounded in verified claims.")


class CriticAgent(BaseAgent):
    """Adversarial agent stress-testing conclusions against evidence gaps and confidence bounds."""

    SYSTEM_PROMPT = (
        "You are the INTELX Chief Red Team Critic.\n"
        "Your duty is to aggressively challenge research conclusions and ungrounded assertions.\n"
        "Identify:\n"
        "1. Conclusions not fully justified by the underlying claims.\n"
        "2. Claims with inflated confidence given single-source or low-tier origins.\n"
        "3. Critical missing angles or neglected counter-hypotheses.\n"
        "Assign a severity rating: LOW (minor caveats), MEDIUM (notable blind spots), "
        "or HIGH (fatal evidentiary deficiencies requiring replanning)."
    )

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        super().__init__(role="critic", name="CriticAgent", gateway=gateway)

    async def execute(
        self,
        draft_findings: list[str | dict[str, Any]],
        claims: list[Claim | dict[str, Any]],
        run_id: str | None = None,
        **kwargs: Any,
    ) -> CritiqueReport:
        """Critique draft findings against available evidence and rate severity."""
        formatted_claims = []
        for c in claims:
            if isinstance(c, dict):
                formatted_claims.append(
                    {"id": c.get("id"), "text": c.get("text"), "confidence": c.get("confidence")}
                )
            else:
                formatted_claims.append({"id": c.id, "text": c.text, "confidence": c.confidence})

        user_prompt = (
            f"DRAFT FINDINGS / CONCLUSIONS:\n"
            f"{json.dumps(draft_findings, indent=2)}\n\n"
            f"AVAILABLE EVIDENCE CLAIMS ({len(formatted_claims)} items):\n"
            f"{json.dumps(formatted_claims, indent=2)}\n\n"
            "Produce an adversarial critique of these findings."
        )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        result = await self.gateway.complete(
            messages=messages,
            role=self.role,
            schema_model=CritiqueReport,
            run_id=run_id,
        )

        return result.parsed
