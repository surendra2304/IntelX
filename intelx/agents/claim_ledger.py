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


def _tokenize(text: str) -> set[str]:
    """Extract lowercase alphanumeric tokens."""
    return set(re.findall(r"\b[a-z0-9]{3,}\b", text.lower()))


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
        """Merge semantically duplicate propositions, combining their evidence references."""
        records = list(self.claims.values())
        to_remove = set()
        merged_count = 0

        for i in range(len(records)):
            rec_a = records[i]
            if rec_a.claim_id in to_remove:
                continue
            tokens_a = _tokenize(rec_a.statement)

            for j in range(i + 1, len(records)):
                rec_b = records[j]
                if rec_b.claim_id in to_remove:
                    continue
                tokens_b = _tokenize(rec_b.statement)

                sim = _jaccard_similarity(tokens_a, tokens_b)
                if sim >= similarity_threshold:
                    # Merge evidence and sources into rec_a
                    combined_evidence = tuple(
                        dict.fromkeys(rec_a.evidence_ids + rec_b.evidence_ids)
                    )
                    combined_sources = tuple(dict.fromkeys(rec_a.source_ids + rec_b.source_ids))
                    rec_a.evidence_ids = combined_evidence
                    rec_a.source_ids = combined_sources
                    rec_a.confidence = max(rec_a.confidence, rec_b.confidence)
                    to_remove.add(rec_b.claim_id)
                    merged_count += 1

        for cid in to_remove:
            self.claims.pop(cid, None)

        return merged_count


__all__ = [
    "ClaimRecord",
    "ClaimLedger",
]
