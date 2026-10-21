"""INTELX Machine-Enforced Citation Verification and Postcondition Gate."""

from __future__ import annotations

import re
from dataclasses import dataclass

from intelx.core.report import (
    export_spoken_citations,
    export_text_citations,
    resolve_citation_id,
)


@dataclass(frozen=True, slots=True)
class CitationCheck:
    """Outcome of citation reference validation across report text."""

    valid: bool
    missing_sources: tuple[str, ...]
    missing_claims: tuple[str, ...]
    dangling_citations: tuple[str, ...] = ()


class CitationValidator:
    """Extracts and validates all [S:id] and [C:id] citation tokens against active repositories."""

    TOKEN_RE = re.compile(r"\[([SC]):([a-zA-Z0-9_-]+)\]")

    def validate(
        self, report_markdown: str, known_sources: set[str], known_claims: set[str]
    ) -> CitationCheck:
        """Scan report text and verify every citation resolves to a known source or claim."""
        matches = self.TOKEN_RE.findall(report_markdown)
        missing_s: list[str] = []
        missing_c: list[str] = []

        for kind, target_id in matches:
            if kind == "S":
                if resolve_citation_id(target_id, known_sources) is None:
                    missing_s.append(target_id)
            elif resolve_citation_id(target_id, known_claims) is None:
                missing_c.append(target_id)

        valid = len(missing_s) == 0 and len(missing_c) == 0
        return CitationCheck(
            valid=valid,
            missing_sources=tuple(sorted(set(missing_s))),
            missing_claims=tuple(sorted(set(missing_c))),
        )

    def repair_or_strip(
        self, report_markdown: str, known_sources: set[str], known_claims: set[str]
    ) -> str:
        """Perform one bounded repair stripping dangling citation references."""

        def _replace_token(m: re.Match) -> str:
            kind, target_id = m.group(1), m.group(2)
            known_ids = known_sources if kind == "S" else known_claims
            if resolve_citation_id(target_id, known_ids) is None:
                return ""
            return m.group(0)

        return self.TOKEN_RE.sub(_replace_token, report_markdown)


__all__ = [
    "CitationCheck",
    "CitationValidator",
    "export_text_citations",
    "export_spoken_citations",
]
