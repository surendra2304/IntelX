"""SQLAlchemy 2.0 Typed Domain and Relational Models for INTELX."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intelx.core.enums import (
    ApiKeyRole,
    ArtifactFormat,
    ArtifactType,
    ClaimOrigin,
    ClaimStatus,
    ClaimType,
    EntityMergeStatus,
    EntityType,
    EvidenceSupportType,
    ReviewDecisionType,
    RunOutcome,
    RunStatus,
    SourceKind,
    TaskErrorClass,
    TaskStatus,
    TaskType,
    TrustTier,
)
from intelx.db.base import Base


def generate_uuid() -> str:
    """Generate a UUID4 hex string for standard primary keys."""
    return uuid.uuid4().hex


def utc_now() -> datetime:
    """Generate timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ResearchRun(Base):
    """Execution container for an end-to-end intelligence investigation."""

    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status_enum", native_enum=False),
        default=RunStatus.QUEUED,
        nullable=False,
        index=True,
    )
    outcome: Mapped[RunOutcome | None] = mapped_column(
        Enum(RunOutcome, name="run_outcome_enum", native_enum=False),
        nullable=True,
    )
    parent_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("research_runs.id"), nullable=True
    )
    plan_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True, index=True
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usd_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="run", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(
        "Event", back_populates="run", cascade="all, delete-orphan"
    )


class Task(Base):
    """Discrete unit of orchestration work dispatched during a research run."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_runs.id"), nullable=False, index=True
    )
    type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, name="task_type_enum", native_enum=False),
        nullable=False,
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status_enum", native_enum=False),
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_class: Mapped[TaskErrorClass | None] = mapped_column(
        Enum(TaskErrorClass, name="task_error_class_enum", native_enum=False),
        nullable=True,
    )
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped["ResearchRun"] = relationship("ResearchRun", back_populates="tasks")


class Source(Base):
    """External information source (web page, document file)."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    kind: Mapped[SourceKind] = mapped_column(
        Enum(SourceKind, name="source_kind_enum", native_enum=False),
        nullable=False,
    )
    location: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    content_type: Mapped[str] = mapped_column(String(128), default="text/html", nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    trust_tier: Mapped[TrustTier] = mapped_column(
        Enum(TrustTier, name="trust_tier_enum", native_enum=False),
        default=TrustTier.QUARANTINE,
        nullable=False,
        index=True,
    )
    robots_ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    license_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    injection_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("research_runs.id"), nullable=True, index=True
    )

    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="source", cascade="all, delete-orphan"
    )


class Document(Base):
    """Normalized textual document extracted from a Source."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    source: Mapped["Source"] = relationship("Source", back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """Indexed textual chunk with exact character slice offsets into document text."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False, index=True
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")


class Entity(Base):
    """Canonical named entity identified during analysis."""

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entity_type_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    created_by_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("research_runs.id"), nullable=True, index=True
    )

    aliases: Mapped[list["EntityAlias"]] = relationship(
        "EntityAlias", back_populates="entity", cascade="all, delete-orphan"
    )


class EntityAlias(Base):
    """Known alias or surface form for a canonical entity."""

    __tablename__ = "entity_aliases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    entity: Mapped["Entity"] = relationship("Entity", back_populates="aliases")


class EntityRelation(Base):
    """Knowledge graph triple between entities."""

    __tablename__ = "entity_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    subject_entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    predicate: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    object_entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    claim_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("claims.id"), nullable=True, index=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)


class EntityMerge(Base):
    """Proposal or record of merging two duplicate entities."""

    __tablename__ = "entity_merges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    kept_entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    merged_entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[EntityMergeStatus] = mapped_column(
        Enum(EntityMergeStatus, name="entity_merge_status_enum", native_enum=False),
        default=EntityMergeStatus.PROPOSED,
        nullable=False,
    )
    created_by_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("research_runs.id"), nullable=True
    )


class Claim(Base):
    """Atomic, structured proposition with verbatim quote and offset verification."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_runs.id"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False, index=True
    )
    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chunks.id"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    predicate: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_type: Mapped[ClaimType] = mapped_column(
        Enum(ClaimType, name="claim_type_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    entities_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    span_end: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    confidence_method: Mapped[str] = mapped_column(
        String(64), default="v1-composite", nullable=False
    )
    origin: Mapped[ClaimOrigin] = mapped_column(
        Enum(ClaimOrigin, name="claim_origin_enum", native_enum=False),
        default=ClaimOrigin.EXTRACTED,
        nullable=False,
    )
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claim_status_enum", native_enum=False),
        default=ClaimStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    superseded_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("claims.id"), nullable=True
    )
    retraction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_agent: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    evidence_items: Mapped[list["Evidence"]] = relationship(
        "Evidence", back_populates="claim", cascade="all, delete-orphan"
    )


class Evidence(Base):
    """Specific textual span supporting or contradicting a Claim."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claims.id"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False, index=True
    )
    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chunks.id"), nullable=False, index=True
    )
    span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    span_end: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    support_type: Mapped[EvidenceSupportType] = mapped_column(
        Enum(EvidenceSupportType, name="evidence_support_type_enum", native_enum=False),
        default=EvidenceSupportType.SUPPORTS,
        nullable=False,
        index=True,
    )
    independent_of_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_by_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_runs.id"), nullable=False, index=True
    )
    created_by_agent: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    claim: Mapped["Claim"] = relationship("Claim", back_populates="evidence_items")


class Finding(Base):
    """Synthesized research conclusion referencing backing claims."""

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_runs.id"), nullable=False, index=True
    )
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_method: Mapped[str] = mapped_column(
        String(64), default="v1-composite", nullable=False
    )
    claim_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    gaps_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    contradictions_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    unverified_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Artifact(Base):
    """Exported research intelligence artifact."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_runs.id"), nullable=False, index=True
    )
    type: Mapped[ArtifactType] = mapped_column(
        Enum(ArtifactType, name="artifact_type_enum", native_enum=False),
        nullable=False,
    )
    format: Mapped[ArtifactFormat] = mapped_column(
        Enum(ArtifactFormat, name="artifact_format_enum", native_enum=False),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), default="v1.0", nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Event(Base):
    """Fine-grained operational and state transition event stream."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("research_runs.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    run: Mapped["ResearchRun"] = relationship("ResearchRun", back_populates="events")

    __table_args__ = (Index("ix_events_run_id_id", "run_id", "id"),)


class AuditEvent(Base):
    """Tamper-evident append-only cryptographic audit ledger."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ReviewDecision(Base):
    """Human or automated governance review decision."""

    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_runs.id"), nullable=False, index=True
    )
    decision: Mapped[ReviewDecisionType] = mapped_column(
        Enum(ReviewDecisionType, name="review_decision_type_enum", native_enum=False),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Policy(Base):
    """Dynamic policy and governance rule configuration."""

    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ApiKey(Base):
    """API authentication key store with hashed secrets."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[ApiKeyRole] = mapped_column(
        Enum(ApiKeyRole, name="api_key_role_enum", native_enum=False),
        default=ApiKeyRole.MEMBER,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
