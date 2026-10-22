# ADR 0002: Deterministic Composite Confidence Scoring Formula (v1)

## Status
Accepted

## Context
Many AI research systems rely on subjective LLM "confidence ratings" (e.g. asking the LLM to give a score from 1-10), which leads to calibration drift, sycophancy, and unexplainable hallucinations. INTELX required a mechanically verifiable, auditable confidence calculation.

## Decision
We implemented the deterministic Composite Confidence Formula v1 in `intelx/core/confidence.py`. Confidence is calculated explicitly from:
1. Originating source trust tier (`TRUSTED` $0.75$, `STANDARD` $0.60$, `QUARANTINE` $0.35$).
2. Independent corroboration boosts ($+0.12$ per independent source evaluated by 3-gram Jaccard overlap $< 0.5$).
3. Penalty deductions for active contradictions ($-0.40$), prompt injection risks ($-0.25$), and stale data ($-0.10$).

## Consequences
### Positive
- **Auditable & Explainable**: Every confidence label (`HIGH`, `MODERATE`, `LOW`) can be inspected with an exact mathematical deduction ledger.
- **Reproducible Evaluation**: Quality gates and CI benchmarks run deterministically with predictable thresholds.

### Negative
- Does not capture nuanced domain-specific rhetorical subtleties that a human domain expert might discern without explicit heuristics.
