"""INTELX Claim to Verbatim Evidence Span Verification Engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Outcome of claim grounding against verbatim document spans."""

    supported: bool
    reason: str
    score: float


class ClaimVerifier:
    """Verifies that extracted claims are grounded by exact character-offset document slices."""

    def verify(
        self,
        claim: Any,
        evidences: dict[str, Any],
        documents: dict[str, str],
    ) -> VerificationResult:
        """Verify claim evidence references against document text."""
        evidence_ids = getattr(claim, "evidence_ids", [])
        if not evidence_ids:
            return VerificationResult(False, "claim has no evidence", 0.0)

        checked = 0
        for eid in evidence_ids:
            ev = evidences.get(eid)
            if not ev:
                continue
            source_id = getattr(ev, "source_id", "")
            doc = documents.get(source_id, "")
            if hasattr(ev, "validate_against") and ev.validate_against(doc):
                checked += 1
            elif hasattr(ev, "verbatim_quote") and hasattr(ev, "start_char") and hasattr(ev, "end_char"):
                if doc and doc[ev.start_char:ev.end_char] == ev.verbatim_quote:
                    checked += 1

        if checked == 0:
            return VerificationResult(False, "no verbatim evidence span validated", 0.0)

        score = min(1.0, checked / max(1, len(evidence_ids)))
        return VerificationResult(True, f"{checked} evidence span(s) validated", score)
