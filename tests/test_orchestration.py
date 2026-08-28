"""Tests for INTELX Orchestration Engine, State Machine, Gates, Worker, and Events."""

from pathlib import Path

import pytest
from sqlalchemy import select

from intelx.agents.extractor import (
    ExtractedClaim,
    ExtractedEntity,
    ExtractionResult,
    ExtractorAgent,
    RelativeSpan,
)
from intelx.agents.scout import ScoutAgent, ScoutOutput, SourceCandidate
from intelx.core.enums import ClaimStatus, ClaimType, RunOutcome, RunStatus
from intelx.core.errors import ValidationError
from intelx.core.settings import Settings
from intelx.db.models import Event, Finding
from intelx.db.repos import ClaimRepo, RunRepo
from intelx.db.session import get_sessionmaker
from intelx.memory.normalize import ingest_and_normalize
from intelx.models.gateway import ModelGateway, Usage
from intelx.orchestration.engine import OrchestrationEngine
from intelx.orchestration.worker import OrchestrationWorker


@pytest.fixture
def db_session_factory():
    """Get active async sessionmaker."""
    return get_sessionmaker()


@pytest.mark.asyncio
async def test_state_machine_invalid_transition_raises(db_session_factory):
    """Verify state machine rejects transitions outside allowed DAG sequences."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session, objective="State machine test")
        engine = OrchestrationEngine()

        # QUEUED -> EXTRACTING is invalid
        with pytest.raises(ValidationError):
            await engine.transition_state(session, run, RunStatus.EXTRACTING)


@pytest.mark.asyncio
async def test_orchestration_green_path(db_session_factory):
    """Verify full end-to-end green path execution via OrchestrationWorker."""
    async with db_session_factory() as session:
        fixture_path = Path("./tests/fixtures/docs/quantum_report.md").resolve()
        run = await RunRepo.create_run(
            session,
            objective="Assess quantum error correction progress",
            scope_json={"domain_hints": [str(fixture_path)]},
        )
        assert run.status == RunStatus.QUEUED
        await session.commit()

        class FixtureScoutAgent(ScoutAgent):
            async def execute(self, subquestion, **kwargs):
                return ScoutOutput(
                    candidates=[
                        SourceCandidate(
                            location=str(fixture_path),
                            title="Quantum Progress Report",
                            reason="Fixture ground truth",
                            expected_relevance=1.0,
                        )
                    ]
                )

        class AccurateExtractor(ExtractorAgent):
            def __init__(self):
                super().__init__()

                class AccurateGateway(ModelGateway):
                    async def complete(
                        self, messages, role="extractor", schema_model=None, **kwargs
                    ):
                        if role == "extractor":
                            ext = ExtractionResult(
                                claims=[
                                    ExtractedClaim(
                                        text=(
                                            "Joint fabrication efforts demonstrated a 40 percent "
                                            "reduction in crosstalk noise."
                                        ),
                                        quote="reduction in crosstalk noise",
                                        relative_span=RelativeSpan(start=0, end=27),
                                        claim_type=ClaimType.FACT,
                                    )
                                ],
                                entities=[ExtractedEntity(name="TSMC", type="ORG")],
                                events=[],
                            )
                            return type(
                                "Res",
                                (),
                                {
                                    "parsed": ext,
                                    "text": ext.model_dump_json(),
                                    "usage": Usage(),
                                    "provider": "mock",
                                    "model": "mock",
                                },
                            )()
                        return await super().complete(
                            messages=messages, role=role, schema_model=schema_model, **kwargs
                        )

                self.gateway = AccurateGateway()

        engine = OrchestrationEngine(
            scout_agent=FixtureScoutAgent(), extractor_agent=AccurateExtractor()
        )
        worker = OrchestrationWorker(engine=engine)

        processed = await worker.run_once(db_session_factory)
        assert processed is True

        async with db_session_factory() as verify_session:
            completed_run = await RunRepo.get_run(verify_session, run.id)
            assert completed_run is not None
            assert completed_run.status == RunStatus.COMPLETED
            assert completed_run.outcome == RunOutcome.ANSWERED
            assert completed_run.completed_at is not None

            events = await RunRepo.get_events_for_run(verify_session, run.id)
            assert len(events) >= 5
            event_types = [e.type for e in events]
            assert "stage.changed" in event_types
            assert "research.completed" in event_types

            stmt_f = select(Finding).where(Finding.run_id == run.id)
            findings = list((await verify_session.execute(stmt_f)).scalars().all())
            assert len(findings) >= 1


@pytest.mark.asyncio
async def test_orchestration_logical_failure_degrades_gracefully(db_session_factory):
    """Verify forced logical failure allows run to complete with recorded degradations."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session, objective="Forced logical failure test")

        class FailingScoutAgent(ScoutAgent):
            async def execute(self, subquestion, **kwargs):
                raise ValueError("Simulated network domain fault")

        engine = OrchestrationEngine(scout_agent=FailingScoutAgent())
        final_run = await engine.execute_run(session=session, run_id=run.id)

        assert final_run.status == RunStatus.COMPLETED
        assert final_run.outcome == RunOutcome.INSUFFICIENT_EVIDENCE

        stmt_ev = select(Event).where(
            Event.run_id == run.id, Event.type == "run.degradations_recorded"
        )
        deg_event = (await session.execute(stmt_ev)).scalar_one_or_none()
        assert deg_event is not None
        assert "degradations" in deg_event.payload_json


@pytest.mark.asyncio
async def test_orchestration_budget_ceiling_gate(db_session_factory):
    """Verify exceeding MAX_RUN_USD halts run immediately with budget.exceeded event."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session, objective="Budget limit test")

        await RunRepo.update_cost_counters(session, run_id=run.id, usd_cost=5.0)

        tiny_budget_settings = Settings(MAX_RUN_USD=0.01)
        engine = OrchestrationEngine(settings=tiny_budget_settings)

        final_run = await engine.execute_run(session=session, run_id=run.id)
        assert final_run.status == RunStatus.FAILED
        assert final_run.outcome == RunOutcome.FAILED

        stmt_ev = select(Event).where(Event.run_id == run.id, Event.type == "budget.exceeded")
        budget_event = (await session.execute(stmt_ev)).scalar_one_or_none()
        assert budget_event is not None


@pytest.mark.asyncio
async def test_orchestration_cancellation_gate(db_session_factory):
    """Verify run cancellation request halts execution."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session, objective="Cancellation test")

        run.error_json = {"cancel_requested": True}
        await session.flush()

        engine = OrchestrationEngine()
        final_run = await engine.execute_run(session=session, run_id=run.id)
        assert final_run.status == RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_orchestration_review_gate_and_resumption(db_session_factory):
    """Verify deep run with disputed claims pauses in REVIEW_REQUIRED until approved."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(
            session,
            objective="Disputed claims review test",
            scope_json={"depth": "deep"},
        )

        fixture_path = Path("./tests/fixtures/docs/sample_battery.txt").resolve()
        text_content = fixture_path.read_text(encoding="utf-8")
        source, doc, chunks, _ = await ingest_and_normalize(
            session=session,
            raw_bytes=text_content.encode("utf-8"),
            location=str(fixture_path),
            kind="FILE",
        )
        quote = "Volumetric energy density"
        sp_start = text_content.index(quote)
        sp_end = sp_start + len(quote)
        await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=source.id,
            document_id=doc.id,
            chunk_id=chunks[0].id,
            text_content="Cell degradation disputed benchmark.",
            quote=quote,
            span_start=sp_start,
            span_end=sp_end,
            claim_type="MEASUREMENT",
            status=ClaimStatus.DISPUTED,
        )

        engine = OrchestrationEngine()
        paused_run = await engine.execute_run(session=session, run_id=run.id)

        assert paused_run.status == RunStatus.REVIEW_REQUIRED

        paused_run.scope_json = {"depth": "deep", "review_decision": "APPROVED"}
        await session.flush()

        resumed_run = await engine.execute_run(session=session, run_id=run.id)
        assert resumed_run.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_orchestration_insufficient_evidence_outcome(db_session_factory):
    """Verify empty evidence produces COMPLETED status with INSUFFICIENT_EVIDENCE and gaps."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session, objective="Null evidence test")

        class EmptyScout(ScoutAgent):
            async def execute(self, subquestion, **kwargs):
                return ScoutOutput(candidates=[])

        engine = OrchestrationEngine(scout_agent=EmptyScout())
        final_run = await engine.execute_run(session=session, run_id=run.id)

        assert final_run.status == RunStatus.COMPLETED
        assert final_run.outcome == RunOutcome.INSUFFICIENT_EVIDENCE

        stmt_f = select(Finding).where(Finding.run_id == run.id)
        findings = list((await session.execute(stmt_f)).scalars().all())
        assert len(findings) >= 1
        assert len(findings[0].gaps_json) >= 1
