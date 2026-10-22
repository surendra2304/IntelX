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
    found_sources: tuple[str, ...] = ()
    found_claims: tuple[str, ...] = ()


def _citation_parts(match: re.Match[str]) -> tuple[str, str]:
    """Return citation kind and identifier for modern and legacy tokens."""
    if match.group(1) is not None:
        return match.group(1), match.group(2)
    legacy_token = match.group(3)
    return legacy_token[0], legacy_token


class CitationValidator:
    """Extracts and validates all [S:id] and [C:id] citation tokens against active repositories."""

    TOKEN_RE = re.compile(r"\[([SC]):([a-zA-Z0-9_-]+)\]|\[([SC]\d+)\]")

    def validate(
        self, report_markdown: str, known_sources: set[str], known_claims: set[str]
    ) -> CitationCheck:
        """Scan report text and verify every citation resolves to a known source or claim."""
        missing_s: list[str] = []
        missing_c: list[str] = []
        found_s: set[str] = set()
        found_c: set[str] = set()

        for match in self.TOKEN_RE.finditer(report_markdown):
            kind, target_id = _citation_parts(match)
            if kind == "S":
                resolved = resolve_citation_id(target_id, known_sources)
                if resolved is None:
                    missing_s.append(target_id)
                else:
                    found_s.add(resolved)
            else:
                resolved = resolve_citation_id(target_id, known_claims)
                if resolved is None:
                    missing_c.append(target_id)
                else:
                    found_c.add(resolved)

        valid = len(missing_s) == 0 and len(missing_c) == 0
        return CitationCheck(
            valid=valid,
            missing_sources=tuple(sorted(set(missing_s))),
            missing_claims=tuple(sorted(set(missing_c))),
            found_sources=tuple(sorted(found_s)),
            found_claims=tuple(sorted(found_c)),
        )

    def repair_or_strip(
        self, report_markdown: str, known_sources: set[str], known_claims: set[str]
    ) -> str:
        """Perform one bounded repair stripping dangling citation references."""

        def _replace_token(m: re.Match) -> str:
            kind, target_id = _citation_parts(m)
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
