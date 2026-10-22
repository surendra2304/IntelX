"""Tests for Contradiction Resolution Engine and Confidence Penalty calculations."""

from intelx.core.contradiction import (
    DISPUTED_CONFIDENCE_CEILING,
    apply_contradiction_resolutions,
    calculate_contradiction_confidence,
    detect_contradictions,
    resolve_claim_conflicts,
)
from intelx.core.enums import ClaimStatus


def test_calculate_contradiction_confidence():
    """Verify confidence is penalized and clamped when contradictions exist."""
    # Uncontested claim retains score
    assert calculate_contradiction_confidence(0.85, has_contradiction=False) == 0.85

    # Single contradiction caps at 0.35 ceiling
    conf1 = calculate_contradiction_confidence(0.90, has_contradiction=True, conflict_count=1)
    assert conf1 <= DISPUTED_CONFIDENCE_CEILING
    assert conf1 == 0.35

    # Multiple contradictions decay further
    conf2 = calculate_contradiction_confidence(0.90, has_contradiction=True, conflict_count=2)
    assert conf2 < conf1
    assert conf2 == round(0.35 * 0.85, 4)

    # Floor clamping
    conf_floor = calculate_contradiction_confidence(0.01, has_contradiction=True, conflict_count=5)
    assert conf_floor >= 0.05


def test_detect_numerical_measurement_contradiction():
    """Contradiction engine detects diverging measurements on same subject."""
    claims = [
        {
            "id": "claim-1",
            "text": "The silicon-anode cell achieved an energy density of 420 Wh/kg at room temperature.",
            "quote": "energy density of 420 Wh/kg",
            "subject": "silicon_anode",
            "confidence": 0.85,
        },
        {
            "id": "claim-2",
            "text": "Independent testing reported the silicon-anode cell achieved only 280 Wh/kg under identical conditions.",
            "quote": "only 280 Wh/kg",
            "subject": "silicon_anode",
            "confidence": 0.80,
        },
    ]

    conflicts = detect_contradictions(claims)
    assert len(conflicts) == 1
    assert conflicts[0].claim_a_id == "claim-1"
    assert conflicts[0].claim_b_id == "claim-2"
    assert conflicts[0].conflict_type == "measurement"
    assert "420" in conflicts[0].reason
    assert "280" in conflicts[0].reason


def test_resolve_claim_conflicts_and_apply():
    """Verify resolve_claim_conflicts returns overrides and apply updates claims in-place."""
    claims = [
        {
            "id": "c-101",
            "text": "Solid-state electrolyte retained 95% capacity after 500 cycles.",
            "quote": "retained 95% capacity after 500 cycles",
            "subject": "solid_state_battery",
            "confidence": 0.90,
            "status": ClaimStatus.ACTIVE,
        },
        {
            "id": "c-102",
            "text": "Solid-state electrolyte retained only 65% capacity after 500 cycles.",
            "quote": "retained only 65% capacity after 500 cycles",
            "subject": "solid_state_battery",
            "confidence": 0.85,
            "status": ClaimStatus.ACTIVE,
        },
        {
            "id": "c-103",
            "text": "The manufacturing facility is located in Austin, Texas.",
            "quote": "facility is located in Austin, Texas",
            "subject": "facility_location",
            "confidence": 0.95,
            "status": ClaimStatus.ACTIVE,
        },
    ]

    conflicts, overrides = resolve_claim_conflicts(claims)
    assert len(conflicts) == 1
    assert "c-101" in overrides
    assert "c-102" in overrides
    assert "c-103" not in overrides

    assert overrides["c-101"] <= DISPUTED_CONFIDENCE_CEILING
    assert overrides["c-102"] <= DISPUTED_CONFIDENCE_CEILING

    # Apply in-place
    apply_contradiction_resolutions(claims, conflicts)
    assert claims[0]["status"] == ClaimStatus.DISPUTED
    assert claims[0]["confidence"] <= DISPUTED_CONFIDENCE_CEILING
    assert claims[1]["status"] == ClaimStatus.DISPUTED
    assert claims[1]["confidence"] <= DISPUTED_CONFIDENCE_CEILING
    assert claims[2]["status"] == ClaimStatus.ACTIVE
    assert claims[2]["confidence"] == 0.95
