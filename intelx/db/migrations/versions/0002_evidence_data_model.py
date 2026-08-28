"""Evidence data model and FTS tables.

Revision ID: 0002_evidence_data_model
Revises: 0001_initial_schema
Create Date: 2026-08-28 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_evidence_data_model"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. research_runs
    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column(
            "parent_run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=True,
        ),
        sa.Column("plan_json", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), unique=True, nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usd_cost", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_runs_status", "research_runs", ["status"])
    op.create_index("ix_research_runs_idempotency_key", "research_runs", ["idempotency_key"])

    # 2. tasks
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error_class", sa.String(length=32), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tasks_run_id", "tasks", ["run_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    # 3. sources
    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), unique=True, nullable=False),
        sa.Column("trust_tier", sa.String(length=32), nullable=False),
        sa.Column("robots_ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("license_note", sa.Text(), nullable=True),
        sa.Column("injection_risk", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_path", sa.Text(), nullable=True),
        sa.Column(
            "created_by_run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_sources_domain", "sources", ["domain"])
    op.create_index("ix_sources_fingerprint", "sources", ["fingerprint"])
    op.create_index("ix_sources_trust_tier", "sources", ["trust_tier"])
    op.create_index("ix_sources_created_by_run_id", "sources", ["created_by_run_id"])

    # 4. documents
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("sources.id"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_source_id", "documents", ["source_id"])

    # 5. chunks
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=36),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])

    # 6. entities
    op.create_table(
        "entities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_by_run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_entities_canonical_name", "entities", ["canonical_name"])
    op.create_index("ix_entities_type", "entities", ["type"])
    op.create_index("ix_entities_created_by_run_id", "entities", ["created_by_run_id"])

    # 7. entity_aliases
    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "entity_id",
            sa.String(length=36),
            sa.ForeignKey("entities.id"),
            nullable=False,
        ),
        sa.Column("alias", sa.String(length=255), nullable=False),
    )
    op.create_index("ix_entity_aliases_entity_id", "entity_aliases", ["entity_id"])
    op.create_index("ix_entity_aliases_alias", "entity_aliases", ["alias"])

    # 8. claims
    op.create_table(
        "claims",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("sources.id"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(length=36),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            sa.String(length=36),
            sa.ForeignKey("chunks.id"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("predicate", sa.String(length=255), nullable=True),
        sa.Column("object", sa.String(length=255), nullable=True),
        sa.Column("claim_type", sa.String(length=32), nullable=False),
        sa.Column("entities_json", sa.JSON(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "confidence_method",
            sa.String(length=64),
            nullable=False,
            server_default="v1-composite",
        ),
        sa.Column("origin", sa.String(length=32), nullable=False, server_default="EXTRACTED"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "superseded_by",
            sa.String(length=36),
            sa.ForeignKey("claims.id"),
            nullable=True,
        ),
        sa.Column("retraction_reason", sa.Text(), nullable=True),
        sa.Column("created_by_agent", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_claims_run_id", "claims", ["run_id"])
    op.create_index("ix_claims_source_id", "claims", ["source_id"])
    op.create_index("ix_claims_document_id", "claims", ["document_id"])
    op.create_index("ix_claims_chunk_id", "claims", ["chunk_id"])
    op.create_index("ix_claims_claim_type", "claims", ["claim_type"])
    op.create_index("ix_claims_status", "claims", ["status"])

    # 9. entity_relations
    op.create_table(
        "entity_relations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "subject_entity_id",
            sa.String(length=36),
            sa.ForeignKey("entities.id"),
            nullable=False,
        ),
        sa.Column("predicate", sa.String(length=128), nullable=False),
        sa.Column(
            "object_entity_id",
            sa.String(length=36),
            sa.ForeignKey("entities.id"),
            nullable=False,
        ),
        sa.Column("claim_id", sa.String(length=36), sa.ForeignKey("claims.id"), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.create_index(
        "ix_entity_relations_subject_entity_id",
        "entity_relations",
        ["subject_entity_id"],
    )
    op.create_index("ix_entity_relations_predicate", "entity_relations", ["predicate"])
    op.create_index(
        "ix_entity_relations_object_entity_id",
        "entity_relations",
        ["object_entity_id"],
    )
    op.create_index("ix_entity_relations_claim_id", "entity_relations", ["claim_id"])

    # 10. entity_merges
    op.create_table(
        "entity_merges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kept_entity_id",
            sa.String(length=36),
            sa.ForeignKey("entities.id"),
            nullable=False,
        ),
        sa.Column(
            "merged_entity_id",
            sa.String(length=36),
            sa.ForeignKey("entities.id"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_by_run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_entity_merges_kept_entity_id", "entity_merges", ["kept_entity_id"])
    op.create_index("ix_entity_merges_merged_entity_id", "entity_merges", ["merged_entity_id"])

    # 11. evidence
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("claim_id", sa.String(length=36), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("sources.id"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(length=36),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            sa.String(length=36),
            sa.ForeignKey("chunks.id"),
            nullable=False,
        ),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("support_type", sa.String(length=32), nullable=False),
        sa.Column("independent_of_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_by_run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=False,
        ),
        sa.Column("created_by_agent", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_claim_id", "evidence", ["claim_id"])
    op.create_index("ix_evidence_source_id", "evidence", ["source_id"])
    op.create_index("ix_evidence_document_id", "evidence", ["document_id"])
    op.create_index("ix_evidence_chunk_id", "evidence", ["chunk_id"])
    op.create_index("ix_evidence_support_type", "evidence", ["support_type"])
    op.create_index("ix_evidence_created_by_run_id", "evidence", ["created_by_run_id"])

    # 12. findings
    op.create_table(
        "findings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=False,
        ),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "confidence_method",
            sa.String(length=64),
            nullable=False,
            server_default="v1-composite",
        ),
        sa.Column("claim_ids_json", sa.JSON(), nullable=False),
        sa.Column("gaps_json", sa.JSON(), nullable=False),
        sa.Column("contradictions_json", sa.JSON(), nullable=False),
        sa.Column("unverified_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_findings_run_id", "findings", ["run_id"])

    # 13. artifacts
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column(
            "schema_version",
            sa.String(length=32),
            nullable=False,
            server_default="v1.0",
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])

    # 14. events
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_run_id_id", "events", ["run_id", "id"])

    # 15. audit_events
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
    )

    # 16. review_decisions
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("research_runs.id"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_review_decisions_run_id", "review_decisions", ["run_id"])

    # 17. policies
    op.create_table(
        "policies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("key", sa.String(length=128), unique=True, nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(length=128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_policies_key", "policies", ["key"])

    # 18. api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("key_hash", sa.String(length=64), unique=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    # 19. Full Text Search (FTS5) for SQLite
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id UNINDEXED, text);")
        op.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(id UNINDEXED, text, quote);"
        )
        # Content synchronization triggers
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS chunks_after_insert AFTER INSERT ON chunks BEGIN "
            "INSERT INTO chunks_fts(id, text) VALUES (new.id, new.text); "
            "END;"
        )
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS chunks_after_delete AFTER DELETE ON chunks BEGIN "
            "DELETE FROM chunks_fts WHERE id = old.id; "
            "END;"
        )
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS claims_after_insert AFTER INSERT ON claims BEGIN "
            "INSERT INTO claims_fts(id, text, quote) VALUES (new.id, new.text, new.quote); "
            "END;"
        )
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS claims_after_delete AFTER DELETE ON claims BEGIN "
            "DELETE FROM claims_fts WHERE id = old.id; "
            "END;"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS claims_after_delete;")
        op.execute("DROP TRIGGER IF EXISTS claims_after_insert;")
        op.execute("DROP TRIGGER IF EXISTS chunks_after_delete;")
        op.execute("DROP TRIGGER IF EXISTS chunks_after_insert;")
        op.execute("DROP TABLE IF EXISTS claims_fts;")
        op.execute("DROP TABLE IF EXISTS chunks_fts;")

    op.drop_table("api_keys")
    op.drop_table("policies")
    op.drop_table("review_decisions")
    op.drop_table("audit_events")
    op.drop_table("events")
    op.drop_table("artifacts")
    op.drop_table("findings")
    op.drop_table("evidence")
    op.drop_table("entity_merges")
    op.drop_table("entity_relations")
    op.drop_table("claims")
    op.drop_table("entity_aliases")
    op.drop_table("entities")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("sources")
    op.drop_table("tasks")
    op.drop_table("research_runs")
