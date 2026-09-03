"""INTELX Final Intelligence Report Quality and Citation Enforcement Gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intelx.agents.citations import CitationValidator


@dataclass(frozen=True, slots=True)
class ReportGate:
    """Evaluation result from the final report quality gate."""

    approved: bool
    reasons: tuple[str, ...]


class FinalReportGate:
    """Enforces strict postconditions on intelligence briefs before final export."""

    def __init__(self, citation_validator: CitationValidator | None = None) -> None:
        self.citation_validator = citation_validator or CitationValidator()

    def evaluate(
        self,
        report_markdown: str,
        sources: set[str],
        claims: set[str],
        min_sources: int = 1,
    ) -> ReportGate:
        """Run all final checks: citation integrity, minimum evidence, and completeness."""
        reasons: list[str] = []

        if not report_markdown or len(report_markdown.strip()) < 50:
            reasons.append("report markdown is empty or too short")

        if len(sources) < min_sources:
            reasons.append(f"insufficient sources: {len(sources)} < {min_sources}")

        cite_check = self.citation_validator.validate(report_markdown, sources, claims)
        if not cite_check.valid:
            if cite_check.missing_sources:
                reasons.append(f"dangling source citations: {cite_check.missing_sources}")
            if cite_check.missing_claims:
                reasons.append(f"dangling claim citations: {cite_check.missing_claims}")

        return ReportGate(
            approved=len(reasons) == 0,
            reasons=tuple(reasons),
        )
