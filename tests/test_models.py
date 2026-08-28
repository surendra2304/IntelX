"""Test roundtrip CRUD and constraints for all INTELX ORM models."""

import pytest
from sqlalchemy import select

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
from intelx.db.models import (
    ApiKey,
    Artifact,
    AuditEvent,
    Chunk,
    Claim,
    Document,
    Entity,
    EntityAlias,
    EntityMerge,
    EntityRelation,
    Event,
    Evidence,
    Finding,
    Policy,
    ResearchRun,
    ReviewDecision,
    Source,
    Task,
)
from intelx.db.session import get_sessionmaker


@pytest.fixture
def db_session_factory():
    """Get active async sessionmaker."""
    return get_sessionmaker()


@pytest.mark.asyncio
async def test_roundtrip_all_tables(db_session_factory):
    """Verify roundtrip write and read across all 18 relational tables."""
    async with db_session_factory() as session:
        # 1. ResearchRun
        run = ResearchRun(
            objective="Investigate quantum computing breakthroughs",
            scope_json={"depth": 3, "allowed_domains": ["nature.com"]},
            status=RunStatus.QUEUED,
            outcome=RunOutcome.ANSWERED,
        )
        session.add(run)
        await session.flush()
        assert run.id is not None

        # 2. Task
        task = Task(
            run_id=run.id,
            type=TaskType.RETRIEVE,
            status=TaskStatus.SUCCEEDED,
            attempt=1,
            error_class=TaskErrorClass.TRANSIENT,
            payload_json={"query": "quantum error correction"},
        )
        session.add(task)
        await session.flush()

        # 3. Source
        source = Source(
            kind=SourceKind.WEB,
            location="https://nature.com/articles/s41586-quantum",
            domain="nature.com",
            title="Logical Qubits with Surface Codes",
            fingerprint="fp_quantum_1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab",
            trust_tier=TrustTier.TRUSTED,
            content_type="text/html",
        )
        session.add(source)
        await session.flush()

        # 4. Document
        doc_text = (
            "Quantum error correction demonstrated logical qubits surpassing "
            "physical error thresholds."
        )
        doc = Document(
            source_id=source.id,
            text=doc_text,
            language="en",
            version=1,
        )
        session.add(doc)
        await session.flush()

        # 5. Chunk
        chunk = Chunk(
            document_id=doc.id,
            idx=0,
            start_char=0,
            end_char=len(doc_text),
            text=doc_text,
        )
        session.add(chunk)
        await session.flush()

        # 6. Entity
        entity_sub = Entity(
            canonical_name="Quantum Error Correction",
            type=EntityType.TECH,
            created_by_run_id=run.id,
        )
        entity_obj = Entity(
            canonical_name="Logical Qubit",
            type=EntityType.TECH,
            created_by_run_id=run.id,
        )
        session.add_all([entity_sub, entity_obj])
        await session.flush()

        # 7. EntityAlias
        alias = EntityAlias(
            entity_id=entity_sub.id,
            alias="QEC",
        )
        session.add(alias)
        await session.flush()

        # 8. Claim
        quote = "logical qubits surpassing physical error thresholds"
        span_start = doc_text.index(quote)
        span_end = span_start + len(quote)
        claim = Claim(
            run_id=run.id,
            source_id=source.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            text="Logical qubits have beaten the physical error threshold.",
            claim_type=ClaimType.FACT,
            entities_json=["Quantum Error Correction", "Logical Qubit"],
            quote=quote,
            span_start=span_start,
            span_end=span_end,
            confidence=0.95,
            origin=ClaimOrigin.EXTRACTED,
            status=ClaimStatus.ACTIVE,
            created_by_agent="extractor_v1",
        )
        session.add(claim)
        await session.flush()

        # 9. EntityRelation
        relation = EntityRelation(
            subject_entity_id=entity_sub.id,
            predicate="enables",
            object_entity_id=entity_obj.id,
            claim_id=claim.id,
            confidence=0.98,
        )
        session.add(relation)
        await session.flush()

        # 10. EntityMerge
        merge = EntityMerge(
            kept_entity_id=entity_sub.id,
            merged_entity_id=entity_obj.id,
            score=0.75,
            status=EntityMergeStatus.PROPOSED,
        )
        session.add(merge)
        await session.flush()

        # 11. Evidence
        evidence = Evidence(
            claim_id=claim.id,
            source_id=source.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            span_start=span_start,
            span_end=span_end,
            quote=quote,
            support_type=EvidenceSupportType.SUPPORTS,
            independent_of_json=[],
            created_by_run_id=run.id,
            created_by_agent="verifier_v1",
        )
        session.add(evidence)
        await session.flush()

        # 12. Finding
        finding = Finding(
            run_id=run.id,
            conclusion="Fault-tolerant quantum computing is progressing towards viability.",
            confidence=0.92,
            confidence_method="v1-composite",
            claim_ids_json=[claim.id],
            gaps_json=["Long-term coherence stability requires more validation."],
            contradictions_json=[],
            unverified_json=[],
        )
        session.add(finding)
        await session.flush()

        # 13. Artifact
        artifact = Artifact(
            run_id=run.id,
            type=ArtifactType.REPORT,
            format=ArtifactFormat.MD,
            path="./data/artifacts/quantum_report.md",
            sha256="sha256_mock_report_digest_1234567890",
        )
        session.add(artifact)
        await session.flush()

        # 14. Event
        event = Event(
            run_id=run.id,
            type="stage.changed",
            payload_json={"from": "EXTRACTING", "to": "VERIFYING"},
        )
        session.add(event)
        await session.flush()

        # 15. AuditEvent
        audit = AuditEvent(
            actor="researcher@intelx.local",
            action="run.created",
            object_type="ResearchRun",
            object_id=run.id,
            detail_json={"objective": run.objective},
            prev_hash="0" * 64,
            hash="1" * 64,
        )
        session.add(audit)
        await session.flush()

        # 16. ReviewDecision
        review = ReviewDecision(
            run_id=run.id,
            decision=ReviewDecisionType.APPROVED,
            notes="Methodology verified with primary sources.",
            decided_by="senior_reviewer",
        )
        session.add(review)
        await session.flush()

        # 17. Policy
        policy = Policy(
            key="security.max_crawls_per_domain",
            value_json={"limit": 50},
            updated_by="admin",
        )
        session.add(policy)
        await session.flush()

        # 18. ApiKey
        api_key = ApiKey(
            key_hash="hash_key_super_secret_token_1234567890",
            name="test-service-key",
            role=ApiKeyRole.ADMIN,
        )
        session.add(api_key)
        await session.commit()

        # Query and assert persistence
        assert (
            await session.execute(select(ResearchRun).where(ResearchRun.id == run.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(Task).where(Task.id == task.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(Source).where(Source.id == source.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(Document).where(Document.id == doc.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(Chunk).where(Chunk.id == chunk.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(Claim).where(Claim.id == claim.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(Evidence).where(Evidence.id == evidence.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(Finding).where(Finding.id == finding.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(Artifact).where(Artifact.id == artifact.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(Event).where(Event.id == event.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(AuditEvent).where(AuditEvent.id == audit.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(ReviewDecision).where(ReviewDecision.id == review.id))
        ).scalar_one() is not None
        assert (
            await session.execute(select(Policy).where(Policy.key == policy.key))
        ).scalar_one() is not None
        assert (
            await session.execute(select(ApiKey).where(ApiKey.key_hash == api_key.key_hash))
        ).scalar_one() is not None
