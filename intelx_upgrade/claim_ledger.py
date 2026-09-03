from __future__ import annotations
from dataclasses import dataclass, field

@dataclass(slots=True)
class ClaimRecord:
    claim_id:str
    statement:str
    evidence_ids:list[str]=field(default_factory=list)
    source_ids:list[str]=field(default_factory=list)
    confidence:float=0.0
    disputed:bool=False
    notes:list[str]=field(default_factory=list)

class ClaimLedger:
    def __init__(self):
        self.claims={}

    def add(self,claim:ClaimRecord)->None:
        if claim.claim_id in self.claims: raise ValueError("duplicate claim")
        self.claims[claim.claim_id]=claim

    def attach_evidence(self,claim_id:str,evidence_id:str,source_id:str)->None:
        c=self.claims[claim_id]
        if evidence_id not in c.evidence_ids:c.evidence_ids.append(evidence_id)
        if source_id not in c.source_ids:c.source_ids.append(source_id)

    def mark_disputed(self,claim_id:str,note:str)->None:
        c=self.claims[claim_id]; c.disputed=True; c.notes.append(note)

    def confidence(self,claim_id:str)->float:
        c=self.claims[claim_id]
        evidence_factor=min(1.0,len(c.evidence_ids)/3)
        source_factor=min(1.0,len(set(c.source_ids))/3)
        dispute_factor=0.45 if c.disputed else 1.0
        c.confidence=round(0.55*evidence_factor+0.45*source_factor,4)*dispute_factor
        return c.confidence
