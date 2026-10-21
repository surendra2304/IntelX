"""Regression tests for malformed and adversarial evidence spans."""

import pytest

from intelx.agents.verification import ClaimVerifier


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("not-an-integer", 4),
        (1.5, 4),
        (True, 4),
        (4, False),
        (-1, 4),
        (2, 2),
        (0, 1000),
        (None, 4),
    ],
)
def test_claim_verifier_rejects_invalid_offsets_without_crashing(start, end):
    verifier = ClaimVerifier()
    result = verifier.verify(
        {"evidence_ids": ["bad-span"]},
        {
            "bad-span": {
                "document_id": "doc-1",
                "span_start": start,
                "span_end": end,
                "quote": "safe",
            }
        },
        {"doc-1": "safe text"},
    )

    assert not result.supported
    assert result.score == 0.0
    assert result.verified_evidence_ids == ()


def test_claim_verifier_skips_invalid_evidence_and_keeps_valid_span():
    verifier = ClaimVerifier()
    text = "Quoted fact is here."
    quote = "Quoted fact"
    start = text.index(quote)
    end = start + len(quote)

    result = verifier.verify(
        {"evidence_ids": ["invalid", "valid", "valid"]},
        {
            "invalid": {
                "document_id": "doc-1",
                "span_start": "oops",
                "span_end": object(),
                "quote": quote,
            },
            "valid": {
                "document_id": "doc-1",
                "span_start": start,
                "span_end": end,
                "quote": quote,
            },
        },
        {"doc-1": text},
    )

    assert result.supported
    assert result.score == 1.0
    assert result.verified_evidence_ids == ("valid",)


def test_claim_verifier_contains_exceptions_from_custom_evidence_validator():
    class BrokenEvidence:
        document_id = "doc-1"
        span_start = "bad"
        span_end = None
        quote = "some quote"

        def validate_against(self, _document_text):
            raise ValueError("malformed evidence record")

    result = ClaimVerifier().verify(
        {"evidence_ids": ["broken"]},
        {"broken": BrokenEvidence()},
        {"doc-1": "a document"},
    )
    assert not result.supported
    assert result.score == 0.0


def test_claim_verifier_uses_start_char_alias_when_span_start_is_none():
    text = "A reliable fact."
    quote = "reliable"
    start = text.index(quote)
    end = start + len(quote)

    result = ClaimVerifier().verify(
        {"evidence_ids": ["alias"]},
        {
            "alias": {
                "document_id": "doc-1",
                "span_start": None,
                "start_char": start,
                "span_end": None,
                "end_char": end,
                "quote": quote,
            }
        },
        {"doc-1": text},
    )
    assert result.supported
    assert result.verified_evidence_ids == ("alias",)
