"""INTELX Enumerations and Core Constants."""

from enum import StrEnum


class RunStatus(StrEnum):
    """Execution status for research runs."""

    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    DISCOVERING = "DISCOVERING"
    RETRIEVING = "RETRIEVING"
    EXTRACTING = "EXTRACTING"
    VERIFYING = "VERIFYING"
    ANALYZING = "ANALYZING"
    SYNTHESIZING = "SYNTHESIZING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunOutcome(StrEnum):
    """Terminal research outcome classification."""

    ANSWERED = "ANSWERED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    FAILED = "FAILED"


class TaskType(StrEnum):
    """Granular task action type."""

    PLAN = "PLAN"
    SCOUT = "SCOUT"
    RETRIEVE = "RETRIEVE"
    EXTRACT = "EXTRACT"
    VERIFY = "VERIFY"
    ANALYZE = "ANALYZE"
    SYNTHESIZE = "SYNTHESIZE"
    CRITIQUE = "CRITIQUE"
    LIBRARIAN = "LIBRARIAN"


class TaskStatus(StrEnum):
    """Execution status of a single orchestration task."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TaskErrorClass(StrEnum):
    """Classification of task execution errors."""

    TRANSIENT = "TRANSIENT"
    LOGICAL = "LOGICAL"


class SourceKind(StrEnum):
    """Source origin type."""

    WEB = "WEB"
    FILE = "FILE"


class TrustTier(StrEnum):
    """Security and credibility tier for sources."""

    QUARANTINE = "QUARANTINE"
    STANDARD = "STANDARD"
    TRUSTED = "TRUSTED"
    BLOCKED = "BLOCKED"


class EntityType(StrEnum):
    """Extracted named entity classification."""

    PERSON = "PERSON"
    ORG = "ORG"
    PRODUCT = "PRODUCT"
    TECH = "TECH"
    PLACE = "PLACE"
    OTHER = "OTHER"


class EntityMergeStatus(StrEnum):
    """Lifecycle state of entity merge proposals."""

    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ClaimType(StrEnum):
    """Semantic claim category."""

    FACT = "FACT"
    MEASUREMENT = "MEASUREMENT"
    EVENT = "EVENT"
    STATEMENT_OF_OPINION = "STATEMENT_OF_OPINION"
    FORECAST = "FORECAST"


class ClaimOrigin(StrEnum):
    """Extraction origin of a claim."""

    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"


class ClaimStatus(StrEnum):
    """Verification and lifecycle state of a claim."""

    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class EvidenceSupportType(StrEnum):
    """Relationship between an evidence span and its parent claim."""

    SUPPORTS = "SUPPORTS"
    PARTIALLY_SUPPORTS = "PARTIALLY_SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CONTEXT = "CONTEXT"


class ArtifactType(StrEnum):
    """Generated research artifact type."""

    REPORT = "REPORT"
    EVIDENCE_PACK = "EVIDENCE_PACK"
    SOURCE_LIST = "SOURCE_LIST"


class ArtifactFormat(StrEnum):
    """File format of generated artifacts."""

    MD = "MD"
    JSON = "JSON"
    CSV = "CSV"


class ReviewDecisionType(StrEnum):
    """Human or automated review gate decision."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApiKeyRole(StrEnum):
    """API key authorization level."""

    ADMIN = "admin"
    MEMBER = "member"
