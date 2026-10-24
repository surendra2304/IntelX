"""
IntelX/deep_research_pipeline.py — IntelX Deep Research Pipeline.

Extends IntelX's capabilities with:
1. Multi-Step Research: break research into stages (broad, deep, verification)
2. Citation Chaining: follow citation graphs to find foundational sources
3. Fact Verification: cross-verify facts against multiple sources
4. Research Plan Generation: auto-generate research plans from questions
5. Knowledge Synthesis: combine findings into comprehensive reports
6. Research Quality Scoring: score research completeness and rigor
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResearchStage:
    """A stage in the research pipeline."""
    stage_id: str
    name: str
    description: str
    query: str
    status: str = "pending"  # pending, running, done
    results: list[dict] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)


@dataclass
class ResearchPlan:
    """A research plan."""
    plan_id: str
    question: str
    stages: list[ResearchStage] = field(default_factory=list)
    status: str = "draft"  # draft, running, done
    created_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class FactCheckResult:
    """A fact verification result."""
    fact: str
    status: str  # verified, unverified, disputed, false
    sources: list[str]
    confidence: float
    conflicts: list[str]


@dataclass
class ResearchReport:
    """A comprehensive research report."""
    question: str
    executive_summary: str
    key_findings: list[str]
    supporting_evidence: list[dict]
    unresolved_questions: list[str]
    confidence_score: float
    source_count: int


class DeepResearchPipeline:
    """Deep multi-stage research pipeline."""

    def __init__(self):
        self._plans: dict[str, ResearchPlan] = {}
        self._fact_checks: dict[str, FactCheckResult] = {}
        self._reports: dict[str, ResearchReport] = {}

    # ── Research Plan Generation ────────────────────────────────────────────

    def generate_plan(
        self,
        question: str,
        depth: str = "thorough",
    ) -> ResearchPlan:
        """Generate a research plan from a question."""
        plan_id = hashlib.md5(
            f"{question}:{time.time()}".encode()
        ).hexdigest()[:12]

        stages = self._create_stages(question, depth)

        plan = ResearchPlan(
            plan_id=plan_id,
            question=question,
            stages=stages,
            status="draft",
            created_at=time.time(),
        )

        self._plans[plan_id] = plan
        return plan

    def _create_stages(self, question: str, depth: str) -> list[ResearchStage]:
        """Create research stages."""
        base_stages = [
            ResearchStage(
                stage_id="1",
                name="Broad Overview",
                description="Get a general understanding of the topic",
                query=f"What is the overview of {question}?",
            ),
            ResearchStage(
                stage_id="2",
                name="Key Concepts",
                description="Identify and research key concepts",
                query=f"What are the key concepts related to {question}?",
            ),
            ResearchStage(
                stage_id="3",
                name="Deep Analysis",
                description="Deep dive into specific aspects",
                query=f"Analyze in detail: {question}",
            ),
            ResearchStage(
                stage_id="4",
                name="Counterarguments",
                description="Find opposing viewpoints",
                query=f"What are the counterarguments to {question}?",
            ),
            ResearchStage(
                stage_id="5",
                name="Verification",
                description="Verify key claims and facts",
                query=f"Verify the key claims about {question}",
            ),
        ]

        if depth == "quick":
            return base_stages[:3]
        elif depth == "thorough":
            return base_stages
        elif depth == "comprehensive":
            base_stages.append(ResearchStage(
                stage_id="6",
                name="Citation Chaining",
                description="Follow citations to foundational sources",
                query=f"Find foundational sources cited in research about {question}",
            ))
            base_stages.append(ResearchStage(
                stage_id="7",
                name="Expert Sources",
                description="Find expert opinions and domain-specific sources",
                query=f"Find expert opinions on {question}",
            ))
            return base_stages

        return base_stages

    # ── Fact Verification ───────────────────────────────────────────────────

    def verify_fact(
        self,
        fact: str,
        sources: list[dict],
    ) -> FactCheckResult:
        """Verify a fact against multiple sources."""
        supporting = []
        contradicting = []
        all_sources = []

        for source in sources:
            text = source.get("text", "").lower()
            fact_lower = fact.lower()

            # Check if source mentions the fact
            if any(word in text for word in fact_lower.split()[:5]):
                all_sources.append(source.get("id", "unknown"))

                # Check sentiment
                sentiment = source.get("sentiment", 0.0)

                if sentiment > 0.3:
                    supporting.append(source.get("id", "unknown"))
                elif sentiment < -0.3:
                    contradicting.append(source.get("id", "unknown"))

        # Determine status
        if not all_sources:
            status = "unverified"
            confidence = 0.0
        elif len(contradicting) > len(supporting):
            status = "disputed"
            confidence = 0.3
        elif len(supporting) >= 2:
            status = "verified"
            confidence = min(0.9, len(supporting) / 5.0)
        elif len(supporting) == 1:
            status = "unverified"
            confidence = 0.3
        else:
            status = "false"
            confidence = 0.1

        result = FactCheckResult(
            fact=fact,
            status=status,
            sources=all_sources,
            confidence=confidence,
            conflicts=contradicting,
        )

        fact_id = hashlib.md5(
            f"{fact}:{time.time()}".encode()
        ).hexdigest()[:12]

        self._fact_checks[fact_id] = result
        return result

    def verify_all_facts(
        self,
        facts: list[str],
        sources: list[dict],
    ) -> list[FactCheckResult]:
        """Verify multiple facts."""
        results = []
        for fact in facts:
            results.append(self.verify_fact(fact, sources))
        return results

    # ── Citation Chaining ───────────────────────────────────────────────────

    def follow_citations(
        self,
        source_id: str,
        max_depth: int = 3,
    ) -> list[str]:
        """Follow citation chain from a source."""
        chain = []
        visited = set()
        queue = [(source_id, 0)]

        while queue:
            current_id, depth = queue.pop(0)

            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)
            chain.append(current_id)

            # In production, this would query a citation database
            # For now, return simulated citations
            if depth < max_depth:
                for i in range(2):
                    new_id = hashlib.md5(
                        f"{current_id}:cite:{i}".encode()
                    ).hexdigest()[:12]
                    queue.append((new_id, depth + 1))

        return chain

    # ── Research Synthesis ──────────────────────────────────────────────────

    def synthesize_research(
        self,
        plan_id: str,
        all_findings: dict[str, list[str]],
        fact_checks: dict[str, FactCheckResult],
    ) -> ResearchReport:
        """Synthesize research findings into a report."""
        plan = self._plans.get(plan_id)
        if not plan:
            return ResearchReport(
                question="N/A",
                executive_summary="Plan not found",
                key_findings=[],
                supporting_evidence=[],
                unresolved_questions=[],
                confidence_score=0.0,
                source_count=0,
            )

        # Collect all findings
        all_findings_list = []
        for stage_id, findings in all_findings.items():
            all_findings_list.extend(findings)

        # Filter verified findings
        verified = []
        for finding in all_findings_list:
            fact_id = hashlib.md5(finding.encode()).hexdigest()[:12]
            check = fact_checks.get(fact_id)
            if check and check.status == "verified":
                verified.append(finding)
            elif not check:
                verified.append(finding)

        # Identify unresolved questions
        unresolved = []
        for fact in all_findings_list:
            fact_id = hashlib.md5(fact.encode()).hexdigest()[:12]
            check = fact_checks.get(fact_id)
            if check and check.status in ("disputed", "unverified"):
                unresolved.append(fact)

        # Calculate confidence
        verified_count = sum(
            1 for c in fact_checks.values() if c.status == "verified"
        )
        total_count = len(fact_checks)
        confidence = verified_count / max(1, total_count) if total_count > 0 else 0.5

        # Write executive summary
        summary = (
            f"This report addresses: '{plan.question}'. "
            f"Based on {len(verified)} key findings across {len(plan.stages)} research stages, "
            f"the research provides a "
            f"{'comprehensive' if confidence > 0.7 else 'partial' if confidence > 0.4 else 'limited'} "
            f"understanding of the topic. "
        )

        if unresolved:
            summary += f"{len(unresolved)} questions remain unresolved."

        report = ResearchReport(
            question=plan.question,
            executive_summary=summary,
            key_findings=verified[:10],
            supporting_evidence=[
                {"finding": f, "stage": sid}
                for sid, findings in all_findings.items()
                for f in findings[:3]
            ],
            unresolved_questions=unresolved[:5],
            confidence_score=confidence,
            source_count=sum(len(c.sources) for c in fact_checks.values()),
        )

        self._reports[plan_id] = report
        return report

    # ── Research Quality Scoring ────────────────────────────────────────────

    def score_research(
        self,
        plan_id: str,
        report: ResearchReport,
    ) -> dict[str, float]:
        """Score research quality."""
        plan = self._plans.get(plan_id)
        if not plan:
            return {"overall": 0.0}

        # Coverage: how many stages completed
        completed = sum(1 for s in plan.stages if s.status == "done")
        coverage = completed / len(plan.stages)

        # Verification: how many facts verified
        total_facts = len(report.key_findings)
        verified = sum(
            1 for f in self._fact_checks.values() if f.status == "verified"
        )
        verification = verified / max(1, total_facts)

        # Depth: number of findings per stage
        findings_per_stage = len(report.key_findings) / max(1, len(plan.stages))
        depth = min(1.0, findings_per_stage / 5.0)

        # Confidence: from report
        confidence = report.confidence_score

        # Overall score
        overall = (
            coverage * 0.25 +
            verification * 0.30 +
            depth * 0.20 +
            confidence * 0.25
        )

        return {
            "overall": overall,
            "coverage": coverage,
            "verification": verification,
            "depth": depth,
            "confidence": confidence,
        }

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_research_report(self) -> dict[str, Any]:
        """Generate a research pipeline report."""
        return {
            "total_plans": len(self._plans),
            "total_fact_checks": len(self._fact_checks),
            "total_reports": len(self._reports),
            "avg_confidence": (
                sum(r.confidence_score for r in self._reports.values()) /
                max(1, len(self._reports))
            ),
        }
