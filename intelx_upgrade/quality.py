from __future__ import annotations
from dataclasses import dataclass
from .models import Claim, Evidence

@dataclass(frozen=True, slots=True)
class QualityReport:
    grounded_claim_rate: float
    independent_source_rate: float
    evidence_coverage: float
    citation_valid: bool
    pass_gate: bool

def evaluate(claims, evidence_by_claim, independent_source_fn, citation_valid=True):
    if not claims:
        return QualityReport(0,0,0,citation_valid,False)
    grounded=sum(bool(evidence_by_claim.get(c.id)) for c in claims)/len(claims)
    independent=sum(independent_source_fn(c) for c in claims)/len(claims)
    coverage=sum(min(1.0,len(evidence_by_claim.get(c.id,[]))/2) for c in claims)/len(claims)
    passed=citation_valid and grounded>=0.9 and coverage>=0.8
    return QualityReport(grounded, independent, coverage, citation_valid, passed)
