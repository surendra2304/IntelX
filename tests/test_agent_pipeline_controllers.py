"""Tests for Autonomous Agent Pipeline Controllers: ClaimLedger, Stopping, Verifier, and Gate."""

from types import SimpleNamespace

from intelx.agents.claim_ledger import ClaimLedger, ClaimRecord
from intelx.agents.report_gate import FinalReportGate
from intelx.agents.research_agent import EvidenceFirstAgent
from intelx.agents.verification import ClaimVerifier


def test_claim_ledger_operations_and_deduplication():
    """Verify registration, retrieval, disputing, filtering, and fuzzy deduplication in ClaimLedger."""
    ledger = ClaimLedger()

    c1 = ClaimRecord(
        claim_id="c-1",
        statement="Sulfide solid-state battery retained 92% capacity over 1,000 cycles.",
        plan_item_id="subq-1",
        evidence_ids=("ev-1",),
        source_ids=("src-1",),
        confidence=0.90,
    )
    # Duplicate with slightly different phrasing
    c2 = ClaimRecord(
        claim_id="c-2",
        statement="Sulfide solid-state battery retained 92% capacity over 1000 cycles.",
        plan_item_id="subq-1",
        evidence_ids=("ev-2",),
        source_ids=("src-2",),
        confidence=0.88,
    )
    c3 = ClaimRecord(
        claim_id="c-3",
        statement="Sodium-ion cathode achieved 160 Wh/kg specific energy.",
        plan_item_id="subq-2",
        evidence_ids=("ev-3",),
        source_ids=("src-3",),
        confidence=0.85,
    )

    ledger.add(c1)
    ledger.add(c2)
    ledger.add(c3)

    assert len(ledger.all()) == 3
    assert len(ledger.supported_claims()) == 3

    # Deduplicate merges c2 into c1
    merged = ledger.deduplicate(similarity_threshold=0.80)
    assert merged == 1
    assert len(ledger.all()) == 2

    retained_c1 = ledger.get("c-1")
    assert retained_c1 is not None
    assert "ev-1" in retained_c1.evidence_ids
    assert "ev-2" in retained_c1.evidence_ids

    # Dispute claim
    ledger.dispute_claim("c-3", reason="conflicting benchmark reported")
    assert retained_c1.status == "SUPPORTED"
    assert ledger.get("c-3").status == "DISPUTED"
    assert ledger.get("c-3").confidence <= 0.35
    assert len(ledger.disputed_claims()) == 1

    # Filter by confidence
    high_conf = ledger.filter_by_confidence(min_confidence=0.80)
    assert len(high_conf) == 1
    assert high_conf[0].claim_id == "c-1"

    # Get by plan item
    subq1_claims = ledger.get_by_plan_item("subq-1")
    assert len(subq1_claims) == 1


def test_report_gate_requires_valid_claim_citations_and_scores_coverage():
    gate = FinalReportGate()
    prose = (
        "# Executive Summary\n\n"
        "This report contains detailed prose and an evidence source reference [S:source-1].\n"
    )
    no_claim_cites = gate.evaluate(
        prose, sources={"source-1"}, claims={"claim-1", "claim-2"}
    )
    assert not no_claim_cites.approved
    assert any("no valid claim citations" in reason for reason in no_claim_cites.reasons)
    assert no_claim_cites.grounding_score == 0.0

    partial = gate.evaluate(
        prose + "\nThe key claim is supported [C:claim-1].\n",
        sources={"source-1"},
        claims={"claim-1", "claim-2"},
    )
    assert partial.approved
    assert partial.grounding_score == 0.5


def test_citation_validator_accepts_legacy_short_tokens():
    from intelx.agents.citations import CitationValidator

    result = CitationValidator().validate(
        "Claim [C1] is backed by sources [S1] and [S2].",
        known_sources={"S1", "S2"},
        known_claims={"C1"},
    )
    assert result.valid
    assert result.found_sources == ("S1", "S2")
    assert result.found_claims == ("C1",)


def test_evidence_first_stopping_controller():
    """Verify EvidenceFirstAgent transitions from PLANNING -> SEARCHING -> EXTRACTING -> SYNTHESIZING."""
    agent = EvidenceFirstAgent()
    plan = ["subq-1", "subq-2"]

    # 1. No plan items -> PLANNING
    d0 = agent.decide([], sources=[], evidence=[], claims=[])
    assert d0.next_status == "PLANNING"

    # 2. Insufficient sources -> SEARCHING
    d1 = agent.decide(plan, sources=[{"id": "src-1"}], evidence=[], claims=[])
    assert d1.next_status == "SEARCHING"
    assert "insufficient sources" in d1.reason

    # 3. Sources present, but no evidence extracted -> EXTRACTING
    sources = [{"id": "src-1"}, {"id": "src-2"}]
    d2 = agent.decide(plan, sources=sources, evidence=[], claims=[])
    assert d2.next_status == "EXTRACTING"

    # 4. Partial coverage: only subq-1 covered -> SEARCHING
    evidence = [{"id": "ev-1"}]
    claims_partial = [
        SimpleNamespace(id="c-1", plan_item_id="subq-1", status="ACTIVE", evidence_ids=["ev-1"])
    ]
    d3 = agent.decide(
        plan, sources=sources, evidence=evidence, claims=claims_partial, min_sources=2
    )
    assert d3.next_status == "SEARCHING"
    assert d3.coverage_ratio == 0.5
    assert "subq-2" in d3.missing_items

    # 5. Full coverage -> SYNTHESIZING
    claims_full = [
        SimpleNamespace(id="c-1", plan_item_id="subq-1", status="ACTIVE", evidence_ids=["ev-1"]),
        SimpleNamespace(id="c-2", plan_item_id="subq-2", status="ACTIVE", evidence_ids=["ev-2"]),
    ]
    d4 = agent.decide(plan, sources=sources, evidence=evidence, claims=claims_full, min_sources=2)
    assert d4.next_status == "SYNTHESIZING"
    assert d4.plan_complete is True
    assert d4.coverage_ratio == 1.0


def test_claim_verifier_verbatim_grounding():
    """Verify ClaimVerifier validates exact character offset spans and rejects hallucinations."""
    verifier = ClaimVerifier()
    doc_text = (
        "The room temperature superconductor showed zero electrical resistance below 125 Kelvin."
    )
    quote = "zero electrical resistance below 125 Kelvin"
    start = doc_text.index(quote)
    end = start + len(quote)

    documents = {"doc-1": doc_text}
    evidences = {
        "ev-valid": {
            "document_id": "doc-1",
            "span_start": start,
            "span_end": end,
            "quote": quote,
        },
        "ev-hallucinated": {
            "document_id": "doc-1",
            "span_start": start,
            "span_end": end,
            "quote": "perpetual motion without power loss",
        },
    }

    # Valid claim
    claim_valid = {"id": "c-1", "evidence_ids": ["ev-valid"]}
    res_valid = verifier.verify(claim_valid, evidences, documents)
    assert res_valid.supported is True
    assert res_valid.score == 1.0
    assert "ev-valid" in res_valid.verified_evidence_ids

    # Hallucinated claim
    claim_invalid = {"id": "c-2", "evidence_ids": ["ev-hallucinated"]}
    res_invalid = verifier.verify(claim_invalid, evidences, documents)
    assert res_invalid.supported is False
    assert res_invalid.score == 0.0

    # Claim with no evidence
    claim_empty = {"id": "c-3", "evidence_ids": []}
    res_empty = verifier.verify(claim_empty, evidences, documents)
    assert res_empty.supported is False


def test_final_report_gate():
    """Verify FinalReportGate verifies length, minimum sources, citations, and sections."""
    gate = FinalReportGate()

    # Empty report
    res_empty = gate.evaluate(report_markdown="", sources=set(), claims=set())
    assert res_empty.approved is False
    assert any("empty or too short" in r for r in res_empty.reasons)

    # Valid report with proper citations and headings
    markdown = """
    # Executive Summary
    Solid-state batteries demonstrate increased safety [S1].

    # Key Findings
    Ionic conductivity was confirmed at 25 mS/cm [C1].

    # Limitations
    Interface impedance requires pressure of 5 MPa [S2].
    """
    sources = {"S1", "S2"}
    claims = {"C1"}
    required_sections = ["Executive Summary", "Key Findings", "Limitations"]

    res_valid = gate.evaluate(
        report_markdown=markdown,
        sources=sources,
        claims=claims,
        min_sources=2,
        required_sections=required_sections,
    )
    assert res_valid.approved is True
    assert res_valid.citation_valid is True
    assert len(res_valid.reasons) == 0

    # Missing required section
    res_missing_sec = gate.evaluate(
        report_markdown=markdown,
        sources=sources,
        claims=claims,
        min_sources=2,
        required_sections=["Executive Summary", "Risk Matrix"],
    )
    assert res_missing_sec.approved is False
    assert any("Risk Matrix" in r for r in res_missing_sec.reasons)
