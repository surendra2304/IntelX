"""INTELX Verifiable Claim Ledger and Proposition Registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


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
