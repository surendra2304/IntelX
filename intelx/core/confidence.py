"""INTELX Deterministic Confidence Formula v1-composite.

===============================================================================
CONFIDENCE SCORING SPECIFICATION (v1-composite):
===============================================================================
Confidence is calculated strictly deterministically from verifiable inputs:

1. Base Tier Score (from the strongest independent supporting source):
   - TRUSTED    : 0.70
   - STANDARD   : 0.50
   - QUARANTINE : 0.20
   - (Default if no independent support: 0.20)

2. Independent Corroborations Bonus:
   + 0.15 * min(independent_corroborations, 3)    [Max bonus: +0.45]

3. Penalties:
   - 0.20 if evidence is stale relative to investigation time range
   - 0.25 if claim is a STATEMENT_OF_OPINION or FORECAST

4. Bounded LLM Semantic Adjustment:
   + clamp(llm_adjustment, -0.10, +0.10) with written rationale

5. Bounds Clamping:
   Final score is strictly clamped to [0.05, 0.95].

6. Qualitative Label Mapping:
   - >= 0.75 : "High"
   - >= 0.50 : "Moderate"
   - >= 0.25 : "Low"
   - < 0.25  : "Very low"
===============================================================================
"""

from typing import Any

from intelx.core.enums import ClaimType, TrustTier

TIER_BASE_SCORES: dict[TrustTier | str, float] = {
    TrustTier.TRUSTED: 0.70,
    "TRUSTED": 0.70,
    TrustTier.STANDARD: 0.50,
    "STANDARD": 0.50,
    TrustTier.QUARANTINE: 0.20,
    "QUARANTINE": 0.20,
    TrustTier.BLOCKED: 0.05,
    "BLOCKED": 0.05,
}


def get_confidence_label(score: float) -> str:
    """Map numeric confidence score to qualitative confidence tier label."""
    if score >= 0.75:
        return "High"
    elif score >= 0.50:
        return "Moderate"
    elif score >= 0.25:
        return "Low"
    return "Very low"


def compute_confidence_score(
    strongest_tier: TrustTier | str | None,
    independent_corroborations: int = 0,
    is_stale: bool = False,
    claim_type: ClaimType | str = ClaimType.FACT,
    llm_adjustment: float = 0.0,
    rationale: str = "",
    credibility_score: float | None = None,
    ai_universe_confidence: float | None = None,
) -> tuple[float, str, dict[str, Any]]:
    """Compute deterministic v1-composite confidence score and qualitative label."""
    # 1. Base tier score
    tier_key = strongest_tier or TrustTier.QUARANTINE
    base = TIER_BASE_SCORES.get(tier_key, 0.20)

    # 2. Corroboration bonus
    corrob_capped = min(max(0, independent_corroborations), 3)
    corrob_bonus = 0.15 * corrob_capped

    # 3. Penalties
    staleness_penalty = 0.20 if is_stale else 0.0
    is_opinion_or_forecast = str(claim_type).upper() in (
        "STATEMENT_OF_OPINION",
        "FORECAST",
        str(ClaimType.STATEMENT_OF_OPINION),
        str(ClaimType.FORECAST),
    )
    opinion_penalty = 0.25 if is_opinion_or_forecast else 0.0

    # 4. Domain Source Credibility Adjustment (-0.10 to +0.10)
    credibility_bonus = 0.0
    if credibility_score is not None:
        credibility_bonus = max(-0.10, min(0.10, (credibility_score - 0.70) * 0.20))

    # 5. Bounded LLM adjustment (-0.10 to +0.10)
    clamped_llm_adj = max(-0.10, min(0.10, llm_adjustment))

    # Raw score computation
    raw_score = (
        base
        + corrob_bonus
        - staleness_penalty
        - opinion_penalty
        + credibility_bonus
        + clamped_llm_adj
    )

    # 6. AI-Universe Multi-Agent Debate Confidence Multiplier
    if ai_universe_confidence is not None:
        clamped_ai_conf = max(0.10, min(1.00, float(ai_universe_confidence)))
        raw_score = raw_score * clamped_ai_conf

    # 7. Clamp to [0.05, 0.95]
    final_score = round(max(0.05, min(0.95, raw_score)), 4)
    label = get_confidence_label(final_score)

    details = {
        "formula": "v1-composite",
        "base_tier": str(tier_key),
        "base_score": base,
        "corroborations_count": independent_corroborations,
        "corroborations_bonus": round(corrob_bonus, 4),
        "credibility_score": credibility_score,
        "credibility_bonus": round(credibility_bonus, 4),
        "ai_universe_confidence": ai_universe_confidence,
        "staleness_penalty": staleness_penalty,
        "opinion_penalty": opinion_penalty,
        "llm_adjustment": round(clamped_llm_adj, 4),
        "rationale": rationale,
        "final_score": final_score,
        "label": label,
    }

    return final_score, label, details
