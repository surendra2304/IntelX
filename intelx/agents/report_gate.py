"""INTELX Final Intelligence Report Quality and Citation Enforcement Gate."""

from __future__ import annotations

import re
from dataclasses import dataclass

from intelx.agents.citations import CitationValidator


@dataclass(frozen=True, slots=True)
class ReportGate:
    """Evaluation result from the final report quality gate."""

    approved: bool
    reasons: tuple[str, ...]
    citation_valid: bool = True
    grounding_score: float = 1.0


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
        min_length: int = 50,
        required_sections: list[str] | None = None,
    ) -> ReportGate:
        """Run all final checks: citation integrity, minimum evidence, and completeness."""
        reasons: list[str] = []

        if not report_markdown or len(report_markdown.strip()) < min_length:
            reasons.append(f"report markdown is empty or too short (< {min_length} chars)")

        if len(sources) < min_sources:
            reasons.append(f"insufficient sources: {len(sources)} < {min_sources}")

        cite_check = self.citation_validator.validate(report_markdown, sources, claims)
        citation_valid = cite_check.valid
        if not cite_check.valid:
            if cite_check.missing_sources:
                reasons.append(f"dangling source citations: {cite_check.missing_sources}")
            if cite_check.missing_claims:
                reasons.append(f"dangling claim citations: {cite_check.missing_claims}")

        if required_sections:
            report_lower = report_markdown.lower()
            for sec in required_sections:
                sec_clean = sec.lower().strip("# ").strip()
                if not re.search(rf"#+\s*{re.escape(sec_clean)}", report_lower):
                    reasons.append(f"missing required section heading: '{sec}'")

        # Grounding score estimation based on presence of citations
        citations_found = len(
            re.findall(r"\[(S\d+|C\d+|src-[a-z0-9_-]+|claim-[a-z0-9_-]+)\]", report_markdown)
        )
        grounding_score = 1.0 if citations_found > 0 or not claims else 0.5

        return ReportGate(
            approved=len(reasons) == 0,
            reasons=tuple(reasons),
            citation_valid=citation_valid,
            grounding_score=grounding_score,
        )


__all__ = [
    "ReportGate",
    "FinalReportGate",
]
