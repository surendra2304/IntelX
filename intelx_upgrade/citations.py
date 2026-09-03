from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CitationCheck:
    valid: bool
    missing: tuple[str,...]
    unsupported: tuple[str,...]

class CitationValidator:
    TOKEN = re.compile(r"\[(?:S|C):([A-Za-z0-9_-]+)\]")

    def validate(self, report: str, valid_ids: set[str]) -> CitationCheck:
        ids = self.TOKEN.findall(report)
        missing = tuple(sorted(set(ids)-valid_ids))
        return CitationCheck(not missing, missing, ())

    def require_evidence_for_claim(self, claim_id: str, evidence_ids: tuple[str,...]) -> None:
        if not evidence_ids: raise ValueError(f"claim {claim_id} has no evidence")
