from __future__ import annotations
from dataclasses import dataclass
from .models import ResearchState, ResearchStatus

@dataclass(frozen=True, slots=True)
class ResearchDecision:
    next_status: ResearchStatus
    reason: str
    plan_complete: bool

class EvidenceFirstAgent:
    def decide(self, state: ResearchState) -> ResearchDecision:
        if state.plan is None:
            return ResearchDecision(ResearchStatus.PLANNING,"no plan exists",False)
        if not state.sources:
            return ResearchDecision(ResearchStatus.SEARCHING,"no sources retained",False)
        if not state.evidence:
            return ResearchDecision(ResearchStatus.SEARCHING,"no evidence retained",False)
        items={e.id for e in state.plan.items}
        covered={c.plan_item_id for c in state.claims if c.evidence_ids}
        missing=items-covered
        if missing:
            return ResearchDecision(ResearchStatus.SEARCHING,f"missing plan coverage: {len(missing)}",False)
        return ResearchDecision(ResearchStatus.SYNTHESIZING,"coverage satisfied",True)
