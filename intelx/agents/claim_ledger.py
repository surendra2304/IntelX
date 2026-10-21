"""INTELX Verifiable Claim Ledger and Proposition Registry."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class ClaimRecord:
    """Individual proposition recorded in the claim ledger."""

    claim_id: str
    statement: str
    plan_item_id: str = ""
    evidence_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    confidence: float = 1.0
    status: str = "SUPPORTED"
    subject: str = ""
    quote: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert claim record to dictionary."""
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "plan_item_id": self.plan_item_id,
            "evidence_ids": list(self.evidence_ids),
            "source_ids": list(self.source_ids),
            "confidence": round(self.confidence, 4),
            "status": self.status,
            "subject": self.subject,
            "quote": self.quote,
            "created_at": self.created_at.isoformat(),
        }


_NUMBER_PATTERN = re.compile(
    r"(?<!\w)\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:%|percent))?(?!\w)",
    re.IGNORECASE,
)
_NEGATION_PATTERN = re.compile(
    r"\b(?:no|not|never|without|neither|nor|cannot|can't|doesn't|don't|didn't|"
    r"isn't|wasn't|weren't|won't|wouldn't|shouldn't|failed|false|denied)\b",
    re.IGNORECASE,
)


def _normalize_number(match: re.Match[str]) -> str:
    """Canonicalize measured values so 1,000 and 1000 compare identically."""
    raw = match.group().casefold().replace(",", "").strip()
    is_percent = raw.endswith("%") or raw.endswith("percent")
    numeric = re.match(r"\d+(?:\.\d+)?", raw)
    if numeric is None:
        return raw
    number = numeric.group()
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    return f"numvalue{number}{'percent' if is_percent else ''}"


def _tokenize(text: str) -> set[str]:
    """Extract normalized tokens while preserving negation and quantitative values."""
    normalized = _NUMBER_PATTERN.sub(_normalize_number, text.casefold())
    tokens = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", normalized)
    negations = {token.replace("’", "'") for token in _NEGATION_PATTERN.findall(text.casefold())}
    return {token for token in tokens if len(token) >= 3 or token in {"no", "nor"}} | negations


def _material_facts(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """Return numeric values and polarity markers that fuzzy deduplication must preserve."""
    normalized = text.casefold().replace("’", "'")
    values = frozenset(_normalize_number(match) for match in _NUMBER_PATTERN.finditer(normalized))
    negations = frozenset(_NEGATION_PATTERN.findall(normalized))
    return values, negations


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Compute Jaccard token overlap between two sets."""
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


class ClaimLedger:
    """Registry maintaining active, contradicted, and disputed claims across research runs."""

    def __init__(self) -> None:
        self.claims: dict[str, ClaimRecord] = {}

    def add(self, claim: ClaimRecord) -> None:
        """Register a claim in the ledger."""
        self.claims[claim.claim_id] = claim

    def get(self, claim_id: str) -> ClaimRecord | None:
        """Retrieve claim by ID."""
        return self.claims.get(claim_id)

    def all(self) -> list[ClaimRecord]:
        """Return list of all registered claims."""
        return list(self.claims.values())

    def supported_claims(self) -> list[ClaimRecord]:
        """Return list of claims with active supporting evidence."""
        return [c for c in self.claims.values() if c.status == "SUPPORTED" and c.evidence_ids]

    def disputed_claims(self) -> list[ClaimRecord]:
        """Return list of disputed claims."""
        return [c for c in self.claims.values() if c.status == "DISPUTED"]

    def dispute_claim(self, claim_id: str, reason: str = "") -> bool:
        """Mark a claim as disputed, reducing confidence to <= 0.35."""
        claim = self.claims.get(claim_id)
        if not claim:
            return False
        claim.status = "DISPUTED"
        claim.confidence = min(claim.confidence, 0.35)
        return True

    def filter_by_confidence(self, min_confidence: float = 0.70) -> list[ClaimRecord]:
        """Return claims whose confidence equals or exceeds the given threshold."""
        return [c for c in self.claims.values() if c.confidence >= min_confidence]

    def get_by_plan_item(self, plan_item_id: str) -> list[ClaimRecord]:
        """Retrieve claims associated with a specific research plan subquestion."""
        return [c for c in self.claims.values() if c.plan_item_id == plan_item_id]

    def deduplicate(self, similarity_threshold: float = 0.85) -> int:
        """Merge only compatible, quantitatively equivalent supported propositions."""
        if (
            isinstance(similarity_threshold, bool)
            or not isinstance(similarity_threshold, (int, float))
            or not 0.0 < similarity_threshold <= 1.0
        ):
            raise ValueError("similarity_threshold must be greater than 0 and at most 1")

        records = list(self.claims.values())
        to_remove: set[str] = set()
        merged_count = 0

        for i, rec_a in enumerate(records):
            if rec_a.claim_id in to_remove:
                continue
            # Disputed/retracted claims are retained as separate audit evidence.
            status_a = rec_a.status.upper()
            if status_a not in {"SUPPORTED", "ACTIVE"}:
                continue
            tokens_a = _tokenize(rec_a.statement)
            material_a = _material_facts(rec_a.statement)

            for rec_b in records[i + 1 :]:
                if rec_b.claim_id in to_remove:
                    continue
                if rec_b.status.upper() != status_a:
                    continue
                if status_a not in {"SUPPORTED", "ACTIVE"}:
                    continue
                if rec_a.plan_item_id and rec_b.plan_item_id and (
                    rec_a.plan_item_id != rec_b.plan_item_id
                ):
                    continue
                if material_a != _material_facts(rec_b.statement):
                    continue

                tokens_b = _tokenize(rec_b.statement)
                sim = _jaccard_similarity(tokens_a, tokens_b)
                if sim < similarity_threshold:
                    continue

                # Merge only compatible claims; retain unique provenance in original order.
                rec_a.evidence_ids = tuple(
                    dict.fromkeys(rec_a.evidence_ids + rec_b.evidence_ids)
                )
                rec_a.source_ids = tuple(
                    dict.fromkeys(rec_a.source_ids + rec_b.source_ids)
                )
                rec_a.confidence = max(rec_a.confidence, rec_b.confidence)
                to_remove.add(rec_b.claim_id)
                merged_count += 1

        for claim_id in to_remove:
            self.claims.pop(claim_id, None)

        return merged_count


__all__ = [
    "ClaimRecord",
    "ClaimLedger",
]
