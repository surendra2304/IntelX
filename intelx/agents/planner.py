"""INTELX Planner Agent: Objective Decomposition, Strategy, and Budget Allocation."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from intelx.agents.base import BaseAgent
from intelx.core.enums import ResearchMode, normalize_research_mode
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class ResearchQuestionEnhancer:
    """Enhances research questions into structured subquestions using domain-specific templates."""

    TEMPLATES: dict[ResearchMode, list[str]] = {
        ResearchMode.SECURITY_RESEARCH: [
            "What specific threat actors, groups, or campaigns have weaponized {subject}, and what are their confirmed operational capabilities?",
            "What is the current in-the-wild exploitation status, proof-of-concept availability, and CVE severity rating for {subject}?",
            "Which MITRE ATT&CK techniques, tactics, and procedures (TTPs) are demonstrated in observed attacks involving {subject}?",
            "What verified detection signatures, IOCs, patch advisories, and defensive mitigation priority rankings exist for {subject}?",
        ],
        ResearchMode.MARKET_RESEARCH: [
            "What primary market-moving events, economic catalysts, and verified dates govern {subject}?",
            "What regulatory filings (SEC/EDGAR), central bank policy shifts, and statutory decisions impact {subject}?",
            "What are the verifiable institutional positioning trends, fund flow dynamics, and liquidity metrics for {subject}?",
            "What macro sentiment drivers, narrative catalysts, and publication indicators are driving pricing momentum in {subject}?",
        ],
        ResearchMode.COMPETITIVE_RESEARCH: [
            "Who are the primary market incumbents and emerging challengers in {subject}, and how are they positioned by market share?",
            "What is the verified feature-by-feature comparison and architectural differentiation across competing solutions in {subject}?",
            "What are the empirical pricing tiers, licensing models, and total cost of ownership benchmarks for {subject}?",
            "What strategic gaps, customer friction points, and competitive vulnerabilities exist across {subject} offerings?",
        ],
        ResearchMode.TECHNICAL_RESEARCH: [
            "What is the core technical architecture, throughput/latency benchmark, and design trade-off of {subject}?",
            "What are the concrete library/framework trade-offs, pros, cons, and dependency overheads in {subject}?",
            "What are the verified production deployment patterns, concurrency models, and security best practices for {subject}?",
            "What are the breaking changes, backward compatibility constraints, and migration path feasibility for {subject}?",
        ],
        ResearchMode.GENERAL: [
            "What are the foundational technical specifications, definitions, and baseline benchmarks of {subject}?",
            "What empirical experimental or operational results have been measured for {subject}?",
            "What verified limitations, disputed claims, or contradictory findings exist regarding {subject}?",
            "What are the primary industry standards and forward-looking developments in {subject}?",
        ],
    }

    @classmethod
    def enhance_question(
        cls,
        raw_question: str,
        domain_hint: str | ResearchMode | None = None,
    ) -> list[str]:
        """Generate at most 4-5 domain-tailored research-grade subquestions."""
        mode = normalize_research_mode(domain_hint)
        templates = cls.TEMPLATES.get(mode, cls.TEMPLATES[ResearchMode.GENERAL])

        subject = raw_question.strip().rstrip("?").rstrip(".")
        if len(subject) > 80:
            subject = subject[:80] + "..."

        subquestions = []
        for tmpl in templates:
            subquestions.append(tmpl.format(subject=subject))

        return subquestions[:5]

    @classmethod
    def get_domain_prompt_instructions(
        cls,
        domain_hint: str | ResearchMode | None = None,
    ) -> str:
        """Return specialized prompt instructions for the Planner LLM."""
        mode = normalize_research_mode(domain_hint)
        if mode == ResearchMode.SECURITY_RESEARCH:
            return (
                "SPECIALIZED DOMAIN: SECURITY RESEARCH (Sentinel Integration)\n"
                "- Decompose query focusing on threat actor capabilities, CVE exploitation status, "
                "MITRE ATT&CK mapping, and defensive mitigation priority rankings."
            )
        elif mode == ResearchMode.MARKET_RESEARCH:
            return (
                "SPECIALIZED DOMAIN: MARKET RESEARCH (Trading Bot Integration)\n"
                "- Decompose query focusing on market-moving events, regulatory policy changes (SEC/Central Banks), "
                "institutional positioning/flow metrics, and sentiment drivers."
            )
        elif mode == ResearchMode.COMPETITIVE_RESEARCH:
            return (
                "SPECIALIZED DOMAIN: COMPETITIVE RESEARCH (Nexus Integration)\n"
                "- Decompose query focusing on competitor landscape, feature comparison matrix, "
                "pricing intelligence/TCO, and strategic gap analysis."
            )
        elif mode == ResearchMode.TECHNICAL_RESEARCH:
            return (
                "SPECIALIZED DOMAIN: TECHNICAL RESEARCH (Forge Integration)\n"
                "- Decompose query focusing on architecture evaluation, library/framework trade-offs, "
                "production patterns, and migration path feasibility."
            )
        return "SPECIALIZED DOMAIN: GENERAL INTELLIGENCE RESEARCH"


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
        """Generate structured research plan adhering to objective, domain templates, and constraints."""
        scope_dict = scope or {}
        domain_hint = (
            scope_dict.get("domain_hint")
            or scope_dict.get("context", {}).get("domain_hint")
            or scope_dict.get("context", {}).get("requesting_system")
        )
        domain_guidance = ResearchQuestionEnhancer.get_domain_prompt_instructions(domain_hint)

        scope_json = json.dumps(scope_dict, indent=2)
        user_prompt = (
            f"RESEARCH OBJECTIVE: {objective}\n\n"
            f"{domain_guidance}\n\n"
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
        plan.objective = objective

        # If domain_hint is present and subquestions are generic, enhance with specialized template
        mode = normalize_research_mode(domain_hint)
        if mode != ResearchMode.GENERAL and (
            not plan.subquestions
            or any(
                "subquestion" in sq.lower() or "aspect" in sq.lower() for sq in plan.subquestions
            )
        ):
            plan.subquestions = ResearchQuestionEnhancer.enhance_question(objective, mode)

        # Enforce max 5 subquestions constraint strictly
        if len(plan.subquestions) > 5:
            plan.subquestions = plan.subquestions[:5]

        return plan
