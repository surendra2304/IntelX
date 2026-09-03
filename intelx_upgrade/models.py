from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import StrEnum
from typing import Any, Mapping
import hashlib, json, time, uuid

class ResearchStatus(StrEnum):
    QUEUED="queued"; PLANNING="planning"; SEARCHING="searching"; FETCHING="fetching"
    EXTRACTING="extracting"; VERIFYING="verifying"; SYNTHESIZING="synthesizing"
    COMPLETE="complete"; FAILED="failed"; CANCELLED="cancelled"; INSUFFICIENT_EVIDENCE="insufficient_evidence"

class SourceTier(StrEnum):
    PRIMARY="primary"; SECONDARY="secondary"; TERTIARY="tertiary"; UNKNOWN="unknown"

class EvidenceType(StrEnum):
    VERBATIM="verbatim"; STRUCTURED="structured"; METADATA="metadata"; NEGATIVE="negative"

@dataclass(frozen=True, slots=True)
class ResearchIdentity:
    tenant_id: str
    actor_id: str
    research_id: str
    correlation_id: str

@dataclass(frozen=True, slots=True)
class ResearchBudget:
    max_sources: int = 50
    max_queries: int = 40
    max_fetches: int = 60
    max_runtime_seconds: int = 1800
    max_cost_usd: float = 10.0
    max_report_chars: int = 120_000

@dataclass(frozen=True, slots=True)
class ResearchPlanItem:
    id: str
    question: str
    required_source_count: int = 2
    required_domain_count: int = 2
    priority: int = 50

@dataclass(frozen=True, slots=True)
class ResearchPlan:
    id: str
    objective: str
    items: tuple[ResearchPlanItem, ...]
    breadth_required: bool = True

@dataclass(frozen=True, slots=True)
class Source:
    id: str
    url: str
    title: str
    domain: str
    tier: SourceTier = SourceTier.UNKNOWN
    published_at: str | None = None
    retrieved_at: float = field(default_factory=time.time)
    content_hash: str | None = None
    canonical_url: str | None = None
    is_syndicated: bool = False

@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    source_id: str
    claim_id: str
    quote: str
    span_start: int
    span_end: int
    evidence_type: EvidenceType = EvidenceType.VERBATIM

    def validate_against(self, document_text: str) -> bool:
        return document_text[self.span_start:self.span_end] == self.quote

@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    statement: str
    plan_item_id: str
    confidence: float
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    disputed: bool = False
    status: str = "active"

@dataclass(frozen=True, slots=True)
class QueryRecord:
    query: str
    plan_item_id: str
    issued_at: float
    result_count: int

@dataclass(frozen=True, slots=True)
class ResearchState:
    identity: ResearchIdentity
    objective: str
    status: ResearchStatus
    plan: ResearchPlan | None
    sources: tuple[Source, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    claims: tuple[Claim, ...] = ()
    queries: tuple[QueryRecord, ...] = ()
    loop: int = 0

    def content_hash(self) -> str:
        payload = {
            "identity": asdict(self.identity), "objective": self.objective,
            "status": self.status.value,
            "plan": asdict(self.plan) if self.plan else None,
            "sources": [asdict(x) for x in self.sources],
            "evidence": [asdict(x) for x in self.evidence],
            "claims": [asdict(x) for x in self.claims],
            "queries": [asdict(x) for x in self.queries],
            "loop": self.loop,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

def stable_id(*parts: str) -> str:
    raw = "\x1f".join(parts).encode()
    return hashlib.sha256(raw).hexdigest()[:32]
