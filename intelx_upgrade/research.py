from __future__ import annotations
from dataclasses import replace
from .models import ResearchState, ResearchStatus, ResearchPlan, ResearchPlanItem, stable_id

class ResearchInvariantError(RuntimeError): pass

class ResearchController:
    """Durable-state-friendly evidence-first research state machine."""

    def transition(self, state: ResearchState, status: ResearchStatus) -> ResearchState:
        allowed = {
            ResearchStatus.QUEUED:{ResearchStatus.PLANNING,ResearchStatus.CANCELLED},
            ResearchStatus.PLANNING:{ResearchStatus.SEARCHING,ResearchStatus.FAILED},
            ResearchStatus.SEARCHING:{ResearchStatus.FETCHING,ResearchStatus.INSUFFICIENT_EVIDENCE,ResearchStatus.FAILED},
            ResearchStatus.FETCHING:{ResearchStatus.EXTRACTING,ResearchStatus.SEARCHING,ResearchStatus.FAILED},
            ResearchStatus.EXTRACTING:{ResearchStatus.VERIFYING,ResearchStatus.SEARCHING,ResearchStatus.FAILED},
            ResearchStatus.VERIFYING:{ResearchStatus.SYNTHESIZING,ResearchStatus.SEARCHING,ResearchStatus.INSUFFICIENT_EVIDENCE,ResearchStatus.FAILED},
            ResearchStatus.SYNTHESIZING:{ResearchStatus.COMPLETE,ResearchStatus.FAILED},
            ResearchStatus.COMPLETE:set(), ResearchStatus.FAILED:set(),
            ResearchStatus.CANCELLED:set(), ResearchStatus.INSUFFICIENT_EVIDENCE:set()
        }
        if status not in allowed.get(state.status,set()):
            raise ResearchInvariantError(f"illegal transition {state.status}->{status}")
        return replace(state, status=status)

    def make_plan(self, state: ResearchState, questions: list[str]) -> ResearchState:
        items = tuple(ResearchPlanItem(stable_id(state.identity.research_id,q), q) for q in questions)
        plan = ResearchPlan(stable_id(state.identity.research_id,"plan"), state.objective, items)
        return replace(state, plan=plan, status=ResearchStatus.SEARCHING)
