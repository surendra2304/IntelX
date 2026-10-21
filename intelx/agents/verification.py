"""INTELX Claim to Verbatim Evidence Span Verification Engine."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger("intelx.verification")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Outcome of claim grounding against verbatim document spans."""

    supported: bool
    reason: str
    score: float
    verified_evidence_ids: tuple[str, ...] = ()


def _field(record: Any, name: str, default: Any = None) -> Any:
    """Read a record field from a mapping or object without coercing its value."""
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _first_field(record: Any, names: tuple[str, ...]) -> Any:
    """Return the first present, non-None field from supported schema aliases."""
    for name in names:
        value = _field(record, name)
        if value is not None:
            return value
    return None


class ClaimVerifier:
    """Verifies extracted claims against exact character-offset document slices."""

    def verify(
        self,
        claim: Any,
        evidences: Mapping[str, Any],
        documents: Mapping[str, str],
    ) -> VerificationResult:
        """Verify evidence spans without letting malformed records abort verification."""
        raw_evidence_ids = _field(claim, "evidence_ids", ())
        if isinstance(raw_evidence_ids, (str, int)) and not isinstance(raw_evidence_ids, bool):
            raw_evidence_ids = (raw_evidence_ids,)
        if not isinstance(raw_evidence_ids, (list, tuple, set, frozenset)):
            return VerificationResult(
                False, "claim evidence references are invalid", 0.0
            )

        evidence_ids = tuple(
            dict.fromkeys(
                str(evidence_id).strip()
                for evidence_id in raw_evidence_ids
                if isinstance(evidence_id, (str, int))
                and not isinstance(evidence_id, bool)
                and str(evidence_id).strip()
            )
        )
        if not evidence_ids:
            return VerificationResult(False, "claim has no evidence references", 0.0)

        if not isinstance(evidences, Mapping) or not isinstance(documents, Mapping):
            return VerificationResult(
                False, "evidence or document repository is invalid", 0.0
            )

        verified_ids: list[str] = []
        for evidence_id in evidence_ids:
            evidence = evidences.get(evidence_id)
            if evidence is None:
                continue

            document_id = _first_field(evidence, ("document_id", "source_id"))
            if document_id is None or not str(document_id).strip():
                continue
            document_text = documents.get(str(document_id), "")
            if not isinstance(document_text, str) or not document_text:
                continue

            quote = _first_field(evidence, ("quote", "verbatim_quote"))
            start = _first_field(evidence, ("span_start", "start_char"))
            end = _first_field(evidence, ("span_end", "end_char"))

            # Offsets must be actual integers, not bools, floats or untrusted strings.
            # Invalid spans are skipped; they must never terminate the whole pipeline.
            offsets_valid = (
                isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(end, int)
                and not isinstance(end, bool)
                and 0 <= start < end <= len(document_text)
            )
            if offsets_valid and isinstance(quote, str) and quote:
                actual_slice = document_text[start:end]
                if actual_slice == quote or actual_slice.strip() == quote.strip():
                    verified_ids.append(evidence_id)
                    continue

            # Some evidence implementations provide a domain-specific verifier.
            # Its failure should invalidate only this evidence item, not the batch.
            validator = _field(evidence, "validate_against")
            if callable(validator):
                try:
                    if validator(document_text):
                        verified_ids.append(evidence_id)
                except Exception as exc:
                    logger.debug(
                        "Evidence span verifier failed for %s (%s)",
                        evidence_id,
                        type(exc).__name__,
                    )

        if not verified_ids:
            return VerificationResult(
                False, "no verbatim evidence span passed offset verification", 0.0
            )

        score = round(len(set(verified_ids)) / len(evidence_ids), 4)
        return VerificationResult(
            supported=True,
            reason=(
                f"{len(set(verified_ids))}/{len(evidence_ids)} "
                "evidence span(s) verbatim verified"
            ),
            score=score,
            verified_evidence_ids=tuple(dict.fromkeys(verified_ids)),
        )


__all__ = [
    "VerificationResult",
    "ClaimVerifier",
]
