"""INTELX Planner Agent: Objective Decomposition, Strategy, and Budget Allocation."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from intelx.agents.base import BaseAgent
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class SourceStrategy(BaseModel):
    """Sourcing configuration and targeting constraints."""

    connector_kinds: list[str] = Field(default_factory=lambda: ["web_search", "file_ingest"])
    domain_hints: list[str] = Field(default_factory=list)
    time_range: str | None = None
    expected_source_count: int = 5


class CompletionCriteria(BaseModel):
    """Sufficiency thresholds for concluding research investigation."""

    min_sources_per_subquestion: int = 2
    min_independent_corroborations: int = 2


class BudgetAllocation(BaseModel):
    """Proportional resource and token budget distribution."""

    scout_pct: float = 0.15
    retrieve_pct: float = 0.20
    extract_pct: float = 0.25
    verify_pct: float = 0.20
    analyze_pct: float = 0.10
    synthesize_pct: float = 0.10


class Plan(BaseModel):
    """Comprehensive research investigation plan."""

    objective: str
    subquestions: list[str] = Field(..., max_length=5)
    source_strategy: SourceStrategy = Field(default_factory=SourceStrategy)
    completion_criteria: CompletionCriteria = Field(default_factory=CompletionCriteria)
    budget_allocation: BudgetAllocation = Field(default_factory=BudgetAllocation)


class PlannerAgent(BaseAgent):
    """Agent decomposing research queries into structured investigation plans."""

    SYSTEM_PROMPT = (
        "You are the INTELX Lead Research Planner.\n"
        "Your objective is to decompose research questions into at most 5 atomic, "
        "evidence-answerable subquestions.\n"
        "Define concrete sourcing strategies, minimum corroboration thresholds, and "
        "budget allocations.\n"
        "Never propose actions beyond the provided research scope."
    )

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        super().__init__(role="planner", name="PlannerAgent", gateway=gateway)

    async def execute(
        self,
        objective: str,
        scope: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> Plan:
        """Generate structured research plan adhering to objective and constraints."""
        scope_json = json.dumps(scope or {}, indent=2)
        user_prompt = (
            f"RESEARCH OBJECTIVE: {objective}\n\n"
            f"INVESTIGATION SCOPE CONSTRAINTS:\n{scope_json}\n\n"
            "Produce a structured research plan with at most 5 focused subquestions."
        )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        result = await self.gateway.complete(
            messages=messages,
            role=self.role,
            schema_model=Plan,
            run_id=run_id,
        )

        plan: Plan = result.parsed
        # Enforce max 5 subquestions constraint strictly
        if len(plan.subquestions) > 5:
            plan.subquestions = plan.subquestions[:5]

        return plan
