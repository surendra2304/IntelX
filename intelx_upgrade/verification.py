from __future__ import annotations
from dataclasses import dataclass
from .models import Claim, Evidence

@dataclass(frozen=True, slots=True)
class VerificationResult:
    supported: bool
    reason: str
    score: float

class ClaimVerifier:
    def verify(self, claim: Claim, evidences: dict[str, Evidence], documents: dict[str, str]) -> VerificationResult:
        if not claim.evidence_ids:
            return VerificationResult(False, "claim has no evidence", 0.0)
        checked = 0
        for eid in claim.evidence_ids:
            ev = evidences.get(eid)
            if not ev: continue
            doc = documents.get(ev.source_id, "")
            if ev.validate_against(doc):
                checked += 1
        if checked == 0:
            return VerificationResult(False, "no verbatim evidence span validated", 0.0)
        score = min(1.0, checked / max(1, len(claim.evidence_ids)))
        return VerificationResult(True, f"{checked} evidence span(s) validated", score)
