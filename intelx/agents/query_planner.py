"""INTELX Query Portfolio Planner for Multi-Angle Targeted Evidence Retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Query:
    """Targeted search query mapped to a subquestion plan item with intent metadata."""

    text: str
    plan_item_id: str
    purpose: str
    priority: int
    source_angle: str


class QueryPortfolioPlanner:
    """Constructs multi-angle query portfolios covering direct, primary, counter-evidence, and temporal dimensions."""

    STOP: set[str] = {
        "what", "are", "the", "and", "for", "with", "from", "that", "this",
        "about", "does", "into", "how", "why", "who", "when", "which"
    }

    def keywords(self, question: str) -> list[str]:
        """Extract high-entropy keyword tokens from question text."""
        words = [w.lower() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", question)]
        return list(dict.fromkeys(w for w in words if w not in self.STOP))[:12]

    def build(self, plan_item_id: str, question: str) -> list[Query]:
        """Generate diverse portfolio of queries for a specific subquestion."""
        k = self.keywords(question)
        base = " ".join(k) if k else question.strip()
        variants = [
            ("direct", base, 80),
            ("primary", f"{base} official report study dataset", 95),
            ("counterevidence", f"{base} criticism limitations contradictory evidence", 90),
            ("recent", f"{base} 2026 latest update", 75),
            ("historical", f"{base} history prior results", 60),
            ("technical", f"{base} methodology measurements benchmark", 85),
        ]
        return [
            Query(text=t, plan_item_id=plan_item_id, purpose=purpose, priority=priority, source_angle=purpose)
            for purpose, t, priority in variants
        ]

    def dedupe(self, queries: list[Query]) -> list[Query]:
        """Deduplicate query collection preserving highest priority."""
        seen: set[str] = set()
        out: list[Query] = []
        for q in sorted(queries, key=lambda x: x.priority, reverse=True):
            key = re.sub(r"\W+", " ", q.text.lower()).strip()
            if key not in seen:
                seen.add(key)
                out.append(q)
        return out
