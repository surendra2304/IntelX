"""Tests for INTELX First Four Agents (Planner, Scout, Retriever, Extractor)."""

from pathlib import Path

import pytest
from sqlalchemy import select

from intelx.agents.extractor import (
    ExtractedClaim,
    ExtractionResult,
    ExtractorAgent,
    RelativeSpan,
)
from intelx.agents.planner import Plan, PlannerAgent
from intelx.agents.retriever import RetrieverAgent
from intelx.agents.scout import ScoutAgent, SourceCandidate
from intelx.core.enums import ClaimType, SourceKind, TaskErrorClass
from intelx.core.settings import Settings
from intelx.db.models import Chunk, Claim, Event
from intelx.db.repos import RunRepo, SourceRepo
from intelx.db.session import get_sessionmaker
from intelx.memory.normalize import ingest_and_normalize
from intelx.models.gateway import ModelGateway
from intelx.models.types import Usage


@pytest.fixture
def db_session_factory():
    """Get active async sessionmaker."""
    return get_sessionmaker()


@pytest.mark.asyncio
async def test_planner_agent_schema_and_subquestion_cap():
    """Verify PlannerAgent generates valid Plan within 5 subquestions cap."""
    agent = PlannerAgent()
    plan = await agent.execute(
        objective="Analyze silicon photonics in next-generation AI datacenter interconnects",
        scope={"depth": 2, "time_range": "2024-2026"},
    )

    assert isinstance(plan, Plan)
    assert len(plan.subquestions) >= 1
    assert len(plan.subquestions) <= 5
    assert plan.source_strategy.expected_source_count > 0
    assert plan.completion_criteria.min_sources_per_subquestion >= 1
    assert plan.budget_allocation.extract_pct > 0.0


@pytest.mark.asyncio
async def test_scout_agent_dedup_and_policy_filtering():
    """Verify ScoutAgent filters already seen URLs and policy-blocked domains."""
    settings = Settings(
        MOCK_MODE=True,
        DOMAIN_DENYLIST=["blocked-domain.com"],
    )
    agent = ScoutAgent(gateway=ModelGateway(settings=settings))

    already_seen = {"https://en.wikipedia.org/wiki/Quantum"}
    output = await agent.execute(
        subquestion="Quantum error correction threshold benchmarks",
        already_seen=already_seen,
    )

    assert len(output.candidates) >= 1
    for c in output.candidates:
        assert c.location not in already_seen
        assert "blocked-domain.com" not in c.location


@pytest.mark.asyncio
async def test_retriever_agent_error_tolerance(db_session_factory):
    """Verify RetrieverAgent handles transient and logical failures gracefully without crashing."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session, objective="Retriever test run")
        fixture_doc = Path("./tests/fixtures/docs/sample_battery.txt").resolve()

        candidates = [
            # 1. Valid local file
            SourceCandidate(
                location=str(fixture_doc),
                title="Solid State Battery Report",
                reason="Local fixture",
            ),
            # 2. Logical failure (non-existent local file)
            SourceCandidate(
                location="file://non_existent_file_xyz123.txt",
                title="Missing File",
                reason="Invalid path",
            ),
            # 3. Logical failure (SSRF / invalid target)
            SourceCandidate(
                location="http://127.0.0.1:9999/private",
                title="Private Loopback",
                reason="Should be rejected by SSRF guard",
            ),
        ]

        retriever = RetrieverAgent()
        output = await retriever.execute(candidates, session=session, run_id=run.id)

        assert len(output.retrieved) == 1
        assert output.retrieved[0].chunks_count >= 1
        assert len(output.failures) == 2

        # Verify failures classified properly
        error_classes = [f.error_class for f in output.failures]
        assert TaskErrorClass.LOGICAL in error_classes


@pytest.mark.asyncio
async def test_extractor_agent_tampered_quote_dropped(db_session_factory):
    """Verify Extractor drops unverifiable/tampered quotes and logs event."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session, objective="Tampered quote test")
        doc_text = "Superconducting qubits require dilution refrigeration below 20 millikelvin."
        source, doc, chunks, _ = await ingest_and_normalize(
            session=session,
            raw_bytes=doc_text.encode("utf-8"),
            location="memory://test_qubits.txt",
            kind=SourceKind.WEB,
            content_type="text/plain",
        )

        # Custom defective gateway returning tampered quote that doesn't exist in chunk
        class DefectiveMockGateway(ModelGateway):
            async def complete(self, messages, **kwargs):
                tampered_extraction = ExtractionResult(
                    claims=[
                        ExtractedClaim(
                            text="Dilution refrigeration is completely optional.",
                            quote="THIS TEXT DOES NOT EXIST IN SOURCE",
                            relative_span=RelativeSpan(start=0, end=33),
                            claim_type=ClaimType.FACT,
                        )
                    ],
                    entities=[],
                    events=[],
                )
                return type(
                    "Res",
                    (),
                    {
                        "parsed": tampered_extraction,
                        "text": tampered_extraction.model_dump_json(),
                        "usage": Usage(),
                    },
                )()

        extractor = ExtractorAgent(gateway=DefectiveMockGateway())
        result = await extractor.execute(
            document=doc,
            chunks=chunks,
            run_id=run.id,
            source_id=source.id,
            session=session,
        )

        # Claim must be dropped
        assert len(result.claims) == 0

        # Event 'claim.rejected_unverifiable' must be recorded in DB
        stmt = select(Event).where(
            Event.run_id == run.id, Event.type == "claim.rejected_unverifiable"
        )
        rejected_event = (await session.execute(stmt)).scalar_one_or_none()
        assert rejected_event is not None
        assert "THIS TEXT DOES NOT EXIST" in str(rejected_event.payload_json)


@pytest.mark.asyncio
async def test_end_to_end_micro_run(db_session_factory):
    """Execute micro pipeline: Plan -> Scout -> Retrieve -> Extract with DB verification."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session, objective="Evaluate solid-state batteries")
        fixture_path = Path("./tests/fixtures/docs/sample_battery.txt").resolve()

        # 1. Planner
        planner = PlannerAgent()
        plan = await planner.execute(
            objective=run.objective,
            scope={"depth": 1},
            run_id=run.id,
        )
        assert len(plan.subquestions) >= 1

        # 2. Scout
        scout = ScoutAgent()
        scout_out = await scout.execute(
            subquestion=plan.subquestions[0],
            plan=plan,
            session=session,
            run_id=run.id,
        )
        assert len(scout_out.candidates) >= 1

        # 3. Retrieve
        # Inject our local fixture path into candidates
        scout_out.candidates.insert(
            0,
            SourceCandidate(
                location=str(fixture_path),
                title="Battery Cycling Lab Data",
                reason="Empirical lab data",
                expected_relevance=1.0,
            ),
        )

        retriever = RetrieverAgent()
        ret_out = await retriever.execute(
            candidates=scout_out.candidates[:2],
            session=session,
            run_id=run.id,
        )
        assert len(ret_out.retrieved) >= 1
        ret_doc_meta = ret_out.retrieved[0]

        # 4. Extract
        doc = await SourceRepo.get_document(session, ret_doc_meta.document_id)
        assert doc is not None

        # Fetch actual persisted chunks for this document
        stmt_db_chunks = select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.idx.asc())
        persisted_chunks = (await session.execute(stmt_db_chunks)).scalars().all()
        assert len(persisted_chunks) >= 1

        # Build valid mock extraction matching exact text
        class AccurateMockGateway(ModelGateway):
            async def complete(self, messages, **kwargs):
                valid_quote = "significant thermal stability"
                rel_start = doc.text.index(valid_quote)
                rel_end = rel_start + len(valid_quote)

                valid_extraction = ExtractionResult(
                    claims=[
                        ExtractedClaim(
                            text="Solid state batteries provide significant thermal stability.",
                            quote=valid_quote,
                            relative_span=RelativeSpan(start=rel_start, end=rel_end),
                            claim_type=ClaimType.FACT,
                            entities=["Solid-state lithium battery"],
                        )
                    ],
                    entities=[],
                    events=[],
                )
                return type(
                    "Res",
                    (),
                    {
                        "parsed": valid_extraction,
                        "text": valid_extraction.model_dump_json(),
                        "usage": Usage(),
                    },
                )()

        extractor = ExtractorAgent(gateway=AccurateMockGateway())
        extract_res = await extractor.execute(
            document=doc,
            chunks=list(persisted_chunks),
            run_id=run.id,
            source_id=ret_doc_meta.source_id,
            session=session,
        )

        assert len(extract_res.claims) == 1

        # Query claims from DB
        stmt_claims = select(Claim).where(Claim.run_id == run.id)
        saved_claims = (await session.execute(stmt_claims)).scalars().all()
        assert len(saved_claims) >= 1

        # Strict span-verbatim verification
        for c in saved_claims:
            assert doc.text[c.span_start : c.span_end] == c.quote
