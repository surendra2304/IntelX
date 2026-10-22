"""Regression tests for honest, task-aware mock synthesis behavior."""

from __future__ import annotations

import json

from intelx.models.providers import MockProvider


def test_mock_critic_abstains_without_claims_and_flags_disputed_claims() -> None:
    no_evidence = MockProvider._mock_critic(
        [{"role": "user", "content": "AVAILABLE EVIDENCE CLAIMS (0 items): []"}]
    )
    assert no_evidence["severity"] == "HIGH"
    assert "must remain unestablished" in no_evidence["summary"]
    assert "well-supported" not in no_evidence["summary"]

    disputed = MockProvider._mock_critic(
        [
            {
                "role": "user",
                "content": 'AVAILABLE EVIDENCE CLAIMS (1 items): [{"status": "DISPUTED"}]',
            }
        ]
    )
    assert disputed["severity"] == "HIGH"
    assert "DISPUTED" in disputed["summary"]
    assert "cannot resolve comparability" in disputed["summary"]


def test_mock_critic_does_not_claim_independent_verification() -> None:
    result = MockProvider._mock_critic(
        [{"role": "user", "content": 'AVAILABLE EVIDENCE CLAIMS (1 items): [{"status": "ACTIVE"}]'}]
    )
    assert result["severity"] == "MEDIUM"
    assert "cannot independently assess source quality" in result["summary"]
    assert "well-supported" not in result["summary"]


def test_mock_synthesis_does_not_return_generic_unrelated_answer_or_gap() -> None:
    objective = "Compare the two reported sodium-ion energy-density benchmarks."
    claims = [
        {
            "id": "claim-one",
            "text": "The tested cathode reached 160 Wh/kg under the stated protocol.",
            "confidence": 0.8,
        }
    ]
    prompt = (
        f"RESEARCH OBJECTIVE: {objective}\n\n"
        f"VERIFIED EVIDENCE CLAIMS ({len(claims)} claims):\n"
        f"{json.dumps(claims, indent=2)}\n\n"
        "Produce the executive answer and key findings."
    )

    result = MockProvider._mock_synthesize([{"role": "user", "content": prompt}])

    assert objective in result["executive_answer"]
    assert "1 verified claim" in result["executive_answer"]
    assert "does not establish comparisons" in result["executive_answer"]
    assert "baseline performance parameters" not in result["executive_answer"]
    assert all("multi-year fleet durability" not in gap for gap in result["gaps"])
    assert result["key_findings"][0]["statement"] == claims[0]["text"]
    assert result["key_findings"][0]["claim_ids"] == ["claim-one"]


def test_mock_synthesis_surfaces_disputed_status_for_comparison_objectives() -> None:
    claims = [
        {
            "id": "claim-420",
            "text": "Silicon anode cell reached 420 Wh/kg.",
            "confidence": 0.8,
            "status": "DISPUTED",
        },
        {
            "id": "claim-310",
            "text": "Silicon anode cell capped at 310 Wh/kg.",
            "confidence": 0.8,
            "status": "DISPUTED",
        },
    ]
    prompt = (
        "RESEARCH OBJECTIVE: Compare the disputed silicon anode measurements.\n\n"
        f"VERIFIED EVIDENCE CLAIMS (2 claims):\n{json.dumps(claims)}\n\n"
        "Produce the executive answer and key findings."
    )

    result = MockProvider._mock_synthesize([{"role": "user", "content": prompt}])

    assert "marked 2 supplied claim(s) as DISPUTED" in result["executive_answer"]
    assert (
        "not proof that the underlying measurements are directly comparable"
        in result["executive_answer"]
    )


def test_mock_synthesis_reports_insufficient_evidence_without_fake_findings() -> None:
    result = MockProvider._mock_synthesize(
        [{"role": "user", "content": "RESEARCH OBJECTIVE: Unknown topic\n\nNo claims."}]
    )

    assert "INSUFFICIENT EVIDENCE" in result["executive_answer"]
    assert result["key_findings"][0]["claim_ids"] == []
