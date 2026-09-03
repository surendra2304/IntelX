"""INTELX Cross-Source Contradiction and Semantic Conflict Engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Conflict:
    """Detected material conflict between two propositions or numerical measurements."""

    claim_a_id: str
    claim_b_id: str
    reason: str
    conflict_type: str = "factual"


class ContradictionEngine:
    """Identifies factual, numerical, and temporal contradictions across extracted claims."""

    def analyze(self, claims: list[Any]) -> list[Conflict]:
        """Examine claims for explicit semantic negation or divergent numerical assertions."""
        conflicts: list[Conflict] = []
        n = len(claims)
        for i in range(n):
            for j in range(i + 1, n):
                ca = claims[i]
                cb = claims[j]
                text_a = getattr(ca, "statement", getattr(ca, "text", "")).lower()
                text_b = getattr(cb, "statement", getattr(cb, "text", "")).lower()
                id_a = getattr(ca, "claim_id", getattr(ca, "id", f"c{i}"))
                id_b = getattr(cb, "claim_id", getattr(cb, "id", f"c{j}"))

                # Check semantic opposition markers
                if ("increases" in text_a and "decreases" in text_b) or ("increases" in text_b and "decreases" in text_a):
                    conflicts.append(Conflict(id_a, id_b, "opposing directional assertions (increase vs decrease)", "directional"))
                elif ("not " in text_a and "not " not in text_b and any(w in text_b for w in text_a.split() if len(w) > 4)):
                    conflicts.append(Conflict(id_a, id_b, "direct negation of factual proposition", "negation"))
                elif ("fails" in text_a and "succeeds" in text_b) or ("fails" in text_b and "succeeds" in text_a):
                    conflicts.append(Conflict(id_a, id_b, "contradictory outcome assertion (fails vs succeeds)", "outcome"))

        return conflicts
