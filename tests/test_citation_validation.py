from intelx.agents.citations import CitationValidator
from intelx.agents.report_gate import FinalReportGate
from intelx.core.report import export_text_citations, format_citation_id, render_report_markdown


def test_report_exports_use_unique_tokens_when_ids_share_eight_char_prefix():
    source_ids = {"source-01aaaaaaaaaaaaaaaaaaaaaaaa", "source-01bbbbbbbbbbbbbbbbbbbbbbbb"}
    claim_ids = {"claim-01aaaaaaaaaaaaaaaaaaaaaaaa", "claim-01bbbbbbbbbbbbbbbbbbbbbbbb"}
    claims = [
        {"id": claim_id, "source_id": source_id, "status": "ACTIVE", "text": "Evidence"}
        for claim_id, source_id in zip(sorted(claim_ids), sorted(source_ids), strict=True)
    ]
    sources = [{"id": source_id, "title": "Evidence source"} for source_id in source_ids]

    markdown = render_report_markdown(
        objective="Assess an evidence-backed finding",
        executive_answer="The evidence supports this finding.",
        grounded_findings=[{"statement": "Evidence supports the result.", "claim_ids": [next(iter(claim_ids))]}],
        unverified_findings=[],
        claims=claims,
        sources=sources,
    )
    findings = [
        {"statement": "Evidence supports the result.", "claim_ids": [claim_id]}
        for claim_id in sorted(claim_ids)
    ]
    text_export = export_text_citations(findings, sources)

    claim_token = format_citation_id(next(iter(claim_ids)), claim_ids)
    assert len(claim_token) > 8
    assert f"[C:{claim_token}]" in markdown
    assert f"[C:{claim_token}]" in text_export
    assert format_citation_id(next(iter(source_ids)), source_ids) in text_export
    validator = CitationValidator()
    assert validator.validate(markdown, source_ids, claim_ids).valid
    assert validator.validate(text_export, source_ids, claim_ids).valid


def test_citation_validator_accepts_exact_ids_and_unique_prefixes():
    result = CitationValidator().validate(
        "Grounded finding [S:source-1234] [C:claim-5678].",
        {"source-12345678"},
        {"claim-56789012"},
    )

    assert result.valid
    assert result.missing_sources == ()
    assert result.missing_claims == ()


def test_citation_validator_rejects_interior_and_ambiguous_matches():
    result = CitationValidator().validate(
        "Finding [S:1234] [C:claim-al].",
        {"source-12345678"},
        {"claim-alpha", "claim-alpine"},
    )

    assert not result.valid
    assert result.missing_sources == ("1234",)
    assert result.missing_claims == ("claim-al",)


def test_repair_strips_unresolvable_citations_but_keeps_unique_prefixes():
    report = "Finding [S:source-12] [S:1234] [C:claim-a]."

    cleaned = CitationValidator().repair_or_strip(
        report,
        {"source-12345678"},
        {"claim-alpha", "claim-alpine"},
    )

    assert cleaned == "Finding [S:source-12]  ."


def test_report_gate_rejects_interior_substring_citation():
    gate = FinalReportGate().evaluate(
        "This report has enough prose to pass the completeness check, but cites [S:1234].",
        {"source-12345678"},
        set(),
    )

    assert not gate.approved
    assert any("dangling source citations" in reason for reason in gate.reasons)
