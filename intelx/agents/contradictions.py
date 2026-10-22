"""INTELX Cross-Source Contradiction and Semantic Conflict Engine.

Re-exports core conflict detection from intelx.core.contradiction for backward compatibility.
"""

from __future__ import annotations

from intelx.core.contradiction import (
    Conflict,
    ContradictionEngine,
    apply_contradiction_resolutions,
    calculate_contradiction_confidence,
    detect_contradictions,
    resolve_claim_conflicts,
)

__all__ = [
    "Conflict",
    "ContradictionEngine",
    "calculate_contradiction_confidence",
    "detect_contradictions",
    "resolve_claim_conflicts",
    "apply_contradiction_resolutions",
]
