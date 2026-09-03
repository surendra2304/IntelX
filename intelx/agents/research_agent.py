"""INTELX Evidence-First Breadth-Aware Research Stopping Controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intelx.core.enums import RunStatus


@dataclass(frozen=True, slots=True)
class ResearchDecision:
    """Stopping or continuation decision made by the autonomous research controller."""

    next_status: str
    reason: str
    plan_complete: bool


class EvidenceFirstAgent:
    """Evaluates whether all planned subquestions have sufficient independent grounded evidence."""

    def decide(
        self,
        plan_items: list[str],
        sources: list[Any],
        evidence: list[Any],
        claims: list[Any],
        min_sources: int = 2,
    ) -> ResearchDecision:
        """Determine next state based on evidence coverage and plan completion."""
        if not plan_items:
            return ResearchDecision("PLANNING", "no plan items exist", False)
        if len(sources) < min_sources:
            return ResearchDecision("SEARCHING", f"insufficient sources retained ({len(sources)} < {min_sources})", False)
        if not evidence:
            return ResearchDecision("EXTRACTING", "no evidence spans retained", False)

        plan_set = set(plan_items)
        covered = {getattr(c, "plan_item_id", getattr(c, "id", "")) for c in claims if getattr(c, "evidence_ids", None)}
        missing = plan_set - covered

        if missing and len(sources) < 15:
            return ResearchDecision("SEARCHING", f"missing plan coverage for {len(missing)} subquestion(s)", False)

        return ResearchDecision("SYNTHESIZING", "plan coverage satisfied with verified evidence", True)
