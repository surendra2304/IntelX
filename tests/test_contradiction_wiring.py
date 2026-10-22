"""Tests for Contradiction Resolution Engine and confidence penalties."""

from intelx.agents.contradictions import (
    apply_contradiction_resolutions,
    calculate_contradiction_confidence,
    detect_contradictions,
    resolve_claim_conflicts,
)
from intelx.core.contradiction import (
    DETERMINISTIC_CONTRADICTION_METHOD,
    DISPUTED_CONFIDENCE_CEILING,
)
from intelx.core.enums import ClaimStatus, ClaimType
from intelx.db.models import Claim


def test_calculate_contradiction_confidence_single_conflict():
    """Verify confidence is capped at ceiling (0.35) for a single contradiction."""
    conf = calculate_contradiction_confidence(
        base_confidence=0.90, has_contradiction=True, conflict_count=1
    )
    assert conf == DISPUTED_CONFIDENCE_CEILING
    assert conf == 0.35


def test_calculate_contradiction_confidence_compounding_decay():
    """Verify multiple contradictions decay confidence further."""
    conf_1 = calculate_contradiction_confidence(
        base_confidence=0.90, has_contradiction=True, conflict_count=1
    )
    conf_2 = calculate_contradiction_confidence(
        base_confidence=0.90, has_contradiction=True, conflict_count=2
    )
    conf_3 = calculate_contradiction_confidence(
        base_confidence=0.90, has_contradiction=True, conflict_count=3
    )

    assert conf_1 == 0.35
    assert conf_2 < conf_1
    assert conf_3 < conf_2
    assert conf_2 == round(0.35 * 0.85, 4)
    assert conf_3 == round(0.35 * (0.85**2), 4)


def test_calculate_contradiction_confidence_no_contradiction():
    """Verify confidence is untouched if no contradiction."""
    conf = calculate_contradiction_confidence(
        base_confidence=0.88, has_contradiction=False, conflict_count=0
    )
    assert conf == 0.88


def test_detect_measurement_contradiction():
    """Verify measurement divergence on same subject is detected as conflict."""
    claims = [
        {
            "id": "c1",
            "text": "The solid-state battery achieved energy density of 450 Wh/kg in testing.",
            "subject": "solid-state battery",
        },
        {
            "id": "c2",
            "text": "The solid-state battery demonstrated energy density of 280 Wh/kg under standard conditions.",
            "subject": "solid-state battery",
        },
    ]
    conflicts = detect_contradictions(claims)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "measurement"
    assert "450 Wh/kg" in conflicts[0].reason
    assert "280 Wh/kg" in conflicts[0].reason


def test_detect_qualitative_contradiction():
    """Verify opposing qualitative assertions on same subject are flagged."""
    claims = [
        {
            "id": "c3",
            "text": "Silicon anode expansion increases battery cycle life substantially.",
            "subject": "silicon anode",
        },
        {
            "id": "c4",
            "text": "Silicon anode expansion decreases battery cycle life due to mechanical stress.",
            "subject": "silicon anode",
        },
    ]
    conflicts = detect_contradictions(claims)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "qualitative"
    assert "opposing directional assertions" in conflicts[0].reason


def test_resolve_claim_conflicts():
    """Verify resolve_claim_conflicts returns both conflict objects and calculated confidence overrides."""
    claims = [
        {
            "id": "c10",
            "text": "Sodium-ion battery achieved 160 Wh/kg cell level energy density.",
            "subject": "sodium-ion battery",
            "confidence": 0.95,
        },
        {
            "id": "c11",
            "text": "Sodium-ion battery delivered 105 Wh/kg cell level energy density.",
            "subject": "sodium-ion battery",
            "confidence": 0.90,
        },
    ]
    conflicts, overrides = resolve_claim_conflicts(claims)
    assert len(conflicts) == 1
    assert "c10" in overrides
    assert "c11" in overrides
    assert overrides["c10"] == 0.35
    assert overrides["c11"] == 0.35


def test_apply_contradiction_resolutions_dict_and_model():
    """Verify apply_contradiction_resolutions mutates claims into DISPUTED status with method and capped confidence."""
    claim_dict = {
        "id": "c20",
        "text": "Quantum processor succeeds at factoring large primes within milliseconds.",
        "subject": "quantum processor",
        "confidence": 0.92,
        "status": ClaimStatus.ACTIVE,
    }
    claim_model = Claim(
        id="c21",
        run_id="run-test",
        source_id="src-test",
        document_id="doc-test",
        text="Quantum processor fails at factoring large primes due to coherence loss.",
        subject="quantum processor",
        confidence=0.88,
        status=ClaimStatus.ACTIVE,
        claim_type=ClaimType.FACT,
    )

    claims = [claim_dict, claim_model]
    conflicts = apply_contradiction_resolutions(claims)

    assert len(conflicts) == 1
    assert claim_dict["status"] == ClaimStatus.DISPUTED
    assert claim_dict["confidence"] == 0.35
    assert claim_dict["confidence_method"] == DETERMINISTIC_CONTRADICTION_METHOD

    assert claim_model.status == ClaimStatus.DISPUTED
    assert claim_model.confidence == 0.35
    assert claim_model.confidence_method == DETERMINISTIC_CONTRADICTION_METHOD
