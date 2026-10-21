"""INTELX Claim to Verbatim Evidence Span Verification Engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Outcome of claim grounding against verbatim document spans."""

    supported: bool
    reason: str
    score: float
    verified_evidence_ids: tuple[str, ...] = ()


class ClaimVerifier:
    """Verifies that extracted claims are grounded by exact character-offset document slices."""

    def verify(
        self,
        claim: Any,
        evidences: dict[str, Any],
        documents: dict[str, str],
    ) -> VerificationResult:
        """Verify claim evidence references against verbatim document text slices."""
        evidence_ids = (
            getattr(claim, "evidence_ids", None)
            or (claim.get("evidence_ids") if isinstance(claim, dict) else None)
            or []
        )
        if not evidence_ids:
            return VerificationResult(False, "claim has no evidence references", 0.0)

        verified_ids: list[str] = []
        for eid in evidence_ids:
            ev = evidences.get(str(eid))
            if not ev:
                continue

            doc_id = (
                getattr(ev, "document_id", None)
                or getattr(ev, "source_id", None)
                or (ev.get("document_id") if isinstance(ev, dict) else None)
                or (ev.get("source_id") if isinstance(ev, dict) else None)
                or ""
            )
            doc_text = documents.get(str(doc_id), "")
            if not doc_text:
                continue

            quote = (
                getattr(ev, "quote", None)
                or getattr(ev, "verbatim_quote", None)
                or (ev.get("quote") if isinstance(ev, dict) else None)
                or (ev.get("verbatim_quote") if isinstance(ev, dict) else None)
                or ""
            )

            start = (
                getattr(ev, "span_start", None)
                if hasattr(ev, "span_start")
                else (
                    getattr(ev, "start_char", None)
                    if hasattr(ev, "start_char")
                    else (
                        ev.get("span_start")
                        if isinstance(ev, dict) and "span_start" in ev
                        else (ev.get("start_char") if isinstance(ev, dict) else None)
                    )
                )
            )

            end = (
                getattr(ev, "span_end", None)
                if hasattr(ev, "span_end")
                else (
                    getattr(ev, "end_char", None)
                    if hasattr(ev, "end_char")
                    else (
                        ev.get("span_end")
                        if isinstance(ev, dict) and "span_end" in ev
                        else (ev.get("end_char") if isinstance(ev, dict) else None)
                    )
                )
            )

            if start is not None and end is not None and quote:
                start = int(start)
                end = int(end)
                if 0 <= start < end <= len(doc_text):
                    actual_slice = doc_text[start:end]
                    if actual_slice == quote:
                        verified_ids.append(str(eid))
                        continue
                    # Graceful whitespace normalized match
                    elif actual_slice.strip() == quote.strip():
                        verified_ids.append(str(eid))
                        continue

            # Fallback if validate_against is implemented
            if hasattr(ev, "validate_against") and callable(ev.validate_against):
                if ev.validate_against(doc_text):
                    verified_ids.append(str(eid))

        if not verified_ids:
            return VerificationResult(
                False, "no verbatim evidence span passed offset verification", 0.0
            )

        score = round(min(1.0, len(verified_ids) / max(1, len(evidence_ids))), 4)
        return VerificationResult(
            supported=True,
            reason=f"{len(verified_ids)}/{len(evidence_ids)} evidence span(s) verbatim verified",
            score=score,
            verified_evidence_ids=tuple(verified_ids),
        )


__all__ = [
    "VerificationResult",
    "ClaimVerifier",
]
