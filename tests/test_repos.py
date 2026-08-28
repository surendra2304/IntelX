"""Tests for Repository operations, span integrity rules, and audit verification."""

import pytest
from sqlalchemy import update

from intelx.core.enums import (
    ClaimType,
    EvidenceSupportType,
    RunStatus,
    SourceKind,
    TrustTier,
)
from intelx.core.errors import IntegrityError
from intelx.db.models import AuditEvent
from intelx.db.repos import AuditChain, ClaimRepo, EvidenceRepo, RunRepo, SourceRepo
from intelx.db.session import get_sessionmaker


@pytest.fixture
def db_session_factory():
    """Get active async sessionmaker."""
    return get_sessionmaker()


@pytest.mark.asyncio
async def test_run_repo_workflow(db_session_factory):
    """Test run creation, atomic job claiming, cost updating, and event logging."""
    async with db_session_factory() as session:
        # 1. Create run
        run = await RunRepo.create_run(
            session=session,
            objective="Analyze global semiconductor supply chains",
            scope_json={"depth": 2},
            created_by="analyst_test",
        )
        assert run.status == RunStatus.QUEUED

        # 2. Atomic job claiming
        claimed_run = await RunRepo.get_or_claim_next_queued_job(session)
        assert claimed_run is not None
        assert claimed_run.id == run.id
        assert claimed_run.status == RunStatus.PLANNING
        assert claimed_run.started_at is not None

        # 3. Update cost counters
        updated_run = await RunRepo.update_cost_counters(
            session=session,
            run_id=run.id,
            input_tokens=1500,
            output_tokens=300,
            usd_cost=0.045,
            tool_calls=3,
        )
        assert updated_run.input_tokens == 1500
        assert updated_run.output_tokens == 300
        assert updated_run.usd_cost == 0.045
        assert updated_run.tool_calls == 3

        # 4. Event logging
        event = await RunRepo.add_event(
            session=session,
            run_id=run.id,
            event_type="stage.completed",
            payload_json={"stage": "PLANNING"},
        )
        assert event.id is not None
        events = await RunRepo.get_events_for_run(session, run.id)
        assert len(events) >= 1
        assert events[0].type == "stage.completed"


@pytest.mark.asyncio
async def test_source_deduplication(db_session_factory):
    """Test source deduplication via unique fingerprint in get_or_create_source."""
    async with db_session_factory() as session:
        fingerprint = "fp_unique_semiconductor_report_abc123"
        location = "https://semiconductors.org/report-2026.pdf"

        # First insert
        s1, created1 = await SourceRepo.get_or_create_source(
            session=session,
            kind=SourceKind.WEB,
            location=location,
            fingerprint=fingerprint,
            title="Semiconductor Industry State 2026",
            trust_tier=TrustTier.STANDARD,
        )
        assert created1 is True
        assert s1.id is not None

        # Second insert with identical fingerprint
        s2, created2 = await SourceRepo.get_or_create_source(
            session=session,
            kind=SourceKind.WEB,
            location=location,
            fingerprint=fingerprint,
            title="Duplicate Entry",
        )
        assert created2 is False
        assert s2.id == s1.id


@pytest.mark.asyncio
async def test_span_integrity_enforcement(db_session_factory):
    """Test claim and evidence span verification: tampered quotes must be rejected."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session=session, objective="Span verification test")
        source = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://example.org/article",
            fingerprint="fp_span_verification_test_987654",
        )

        doc_text = (
            "Taiwan Semiconductor Manufacturing Co accounts for over 50 percent "
            "of global foundry revenue."
        )
        doc = await SourceRepo.create_document(
            session=session, source_id=source.id, text_content=doc_text
        )
        chunk = await SourceRepo.create_chunk(
            session=session,
            document_id=doc.id,
            idx=0,
            start_char=0,
            end_char=len(doc_text),
            text_content=doc_text,
        )

        # 1. Valid Claim creation
        valid_quote = "over 50 percent of global foundry revenue"
        span_start = doc_text.index(valid_quote)
        span_end = span_start + len(valid_quote)

        claim = await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=source.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            text_content="TSMC commands majority foundry market share.",
            quote=valid_quote,
            span_start=span_start,
            span_end=span_end,
            claim_type=ClaimType.MEASUREMENT,
        )
        assert claim.id is not None
        assert claim.quote == valid_quote

        # 2. Tampered Claim Quote (should raise IntegrityError)
        tampered_quote = "over 90 percent of global foundry revenue"
        with pytest.raises(IntegrityError) as exc_claim:
            await ClaimRepo.create_claim(
                session=session,
                run_id=run.id,
                source_id=source.id,
                document_id=doc.id,
                chunk_id=chunk.id,
                text_content="TSMC commands 90% foundry share.",
                quote=tampered_quote,
                span_start=span_start,
                span_end=span_end,
                claim_type=ClaimType.MEASUREMENT,
            )
        assert "Claim span verification failed" in str(exc_claim.value)

        # 3. Valid Evidence creation
        evidence = await EvidenceRepo.create_evidence(
            session=session,
            claim_id=claim.id,
            source_id=source.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            span_start=span_start,
            span_end=span_end,
            quote=valid_quote,
            support_type=EvidenceSupportType.SUPPORTS,
            created_by_run_id=run.id,
            created_by_agent="verifier",
        )
        assert evidence.id is not None

        # 4. Tampered Evidence Quote (should raise IntegrityError)
        with pytest.raises(IntegrityError) as exc_ev:
            await EvidenceRepo.create_evidence(
                session=session,
                claim_id=claim.id,
                source_id=source.id,
                document_id=doc.id,
                chunk_id=chunk.id,
                span_start=span_start,
                span_end=span_end,
                quote="Tampered quote content",
                support_type=EvidenceSupportType.SUPPORTS,
                created_by_run_id=run.id,
                created_by_agent="verifier",
            )
        assert "Evidence span verification failed" in str(exc_ev.value)


@pytest.mark.asyncio
async def test_audit_chain_tamper_detection(db_session_factory):
    """Test cryptographic audit chain verification and tamper detection."""
    async with db_session_factory() as session:
        # 1. Append 3 audit events
        await AuditChain.append_event(
            session=session,
            actor="admin",
            action="policy.created",
            object_type="Policy",
            object_id="pol_1",
            detail_json={"rule": "rate_limit_100"},
        )
        e2 = await AuditChain.append_event(
            session=session,
            actor="analyst",
            action="run.started",
            object_type="ResearchRun",
            object_id="run_101",
            detail_json={"depth": 3},
        )
        await AuditChain.append_event(
            session=session,
            actor="supervisor",
            action="review.approved",
            object_type="ReviewDecision",
            object_id="rev_501",
            detail_json={"decision": "APPROVED"},
        )
        await session.commit()

        # 2. Verify untampered chain
        is_valid, errors = await AuditChain.verify(session)
        assert is_valid is True
        assert len(errors) == 0

        # 3. Introduce malicious modification to event e2 details
        stmt = (
            update(AuditEvent)
            .where(AuditEvent.id == e2.id)
            .values(detail_json={"depth": 9999, "malicious_injection": True})
        )
        await session.execute(stmt)
        await session.commit()

        # 4. Verify tampering is detected immediately
        is_valid_after, errors_after = await AuditChain.verify(session)
        assert is_valid_after is False
        assert len(errors_after) >= 1
        assert f"Tampered record at audit event id={e2.id}" in errors_after[0]


@pytest.mark.asyncio
async def test_full_text_search(db_session_factory):
    """Test FTS text search across chunks and claims."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session=session, objective="FTS search validation")
        source = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://wikipedia.org/wiki/Artificial_Intelligence",
            fingerprint="fp_ai_wikipedia_fts_test_123",
        )

        doc_text = (
            "Transformers are neural network architectures utilizing multi-head "
            "self-attention mechanisms."
        )
        doc = await SourceRepo.create_document(
            session=session, source_id=source.id, text_content=doc_text
        )
        chunk = await SourceRepo.create_chunk(
            session=session,
            document_id=doc.id,
            idx=0,
            start_char=0,
            end_char=len(doc_text),
            text_content=doc_text,
        )

        quote = "multi-head self-attention mechanisms"
        span_start = doc_text.index(quote)
        span_end = span_start + len(quote)

        claim = await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=source.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            text_content="Self-attention mechanisms power modern transformer models.",
            quote=quote,
            span_start=span_start,
            span_end=span_end,
            claim_type=ClaimType.FACT,
        )
        await session.commit()

        # Search chunks and claims
        matching_chunks = await ClaimRepo.search_chunks_fts(session, "Transformers")
        assert len(matching_chunks) >= 1
        assert any(c.id == chunk.id for c in matching_chunks)

        matching_claims = await ClaimRepo.search_claims_fts(session, "transformer")
        assert len(matching_claims) >= 1
        assert any(c.id == claim.id for c in matching_claims)
