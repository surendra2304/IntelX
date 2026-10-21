"""INTELX Evidence-First Breadth-Aware Research Stopping Controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResearchDecision:
    """Stopping or continuation decision made by the autonomous research controller."""

    next_status: str
    reason: str
    plan_complete: bool
    coverage_ratio: float = 0.0
    covered_items: tuple[str, ...] = ()
    missing_items: tuple[str, ...] = ()


class EvidenceFirstAgent:
    """Evaluates whether all planned subquestions have sufficient independent grounded evidence."""

    def decide(
        self,
        plan_items: list[str],
        sources: list[Any],
        evidence: list[Any],
        claims: list[Any],
        min_sources: int = 2,
        max_sources: int = 25,
        target_claims_per_item: int = 1,
    ) -> ResearchDecision:
        """Determine next research lifecycle phase based on evidence coverage and diminishing returns."""
        if not plan_items:
            return ResearchDecision("PLANNING", "no plan items exist", False, 0.0)

        plan_set = [str(item).strip() for item in plan_items if str(item).strip()]
        if not plan_set:
            return ResearchDecision("PLANNING", "plan items empty", False, 0.0)

        if len(sources) < min_sources:
            return ResearchDecision(
                "SEARCHING",
                f"insufficient sources retained ({len(sources)} < {min_sources})",
                False,
                0.0,
                (),
                tuple(plan_set),
            )

        if not evidence:
            return ResearchDecision(
                "EXTRACTING",
                "sources available but no verified evidence spans extracted yet",
                False,
                0.0,
                (),
                tuple(plan_set),
            )

        # Map claims to plan items
        claim_plan_counts: dict[str, int] = {}
        for c in claims:
            status = str(
                getattr(c, "status", "ACTIVE")
                if hasattr(c, "status")
                else (c.get("status", "ACTIVE") if isinstance(c, dict) else "ACTIVE")
            ).upper()
            if status in ("RETRACTED", "SUPERSEDED"):
                continue
            plan_id = str(
                getattr(c, "plan_item_id", "")
                if hasattr(c, "plan_item_id")
                else (c.get("plan_item_id", "") if isinstance(c, dict) else "")
            )
            if plan_id:
                claim_plan_counts[plan_id] = claim_plan_counts.get(plan_id, 0) + 1

        covered: list[str] = []
        missing: list[str] = []
        for item in plan_set:
            if claim_plan_counts.get(item, 0) >= target_claims_per_item:
                covered.append(item)
            else:
                missing.append(item)

        coverage_ratio = len(covered) / len(plan_set) if plan_set else 1.0

        # Diminishing returns or source cap reached
        if len(sources) >= max_sources:
            return ResearchDecision(
                "SYNTHESIZING",
                f"maximum source budget reached ({len(sources)}/{max_sources}); proceeding with available evidence",
                plan_complete=(len(missing) == 0),
                coverage_ratio=coverage_ratio,
                covered_items=tuple(covered),
                missing_items=tuple(missing),
            )

        # Missing coverage and capacity remains
        if missing and len(sources) < max_sources:
            return ResearchDecision(
                "SEARCHING",
                f"missing plan coverage for {len(missing)} subquestion(s) ({coverage_ratio:.0%} covered)",
                plan_complete=False,
                coverage_ratio=coverage_ratio,
                covered_items=tuple(covered),
                missing_items=tuple(missing),
            )

        return ResearchDecision(
            "SYNTHESIZING",
            f"plan coverage fully satisfied with verified evidence ({coverage_ratio:.0%})",
            plan_complete=True,
            coverage_ratio=coverage_ratio,
            covered_items=tuple(covered),
            missing_items=tuple(missing),
        )


__all__ = [
    "ResearchDecision",
    "EvidenceFirstAgent",
]
