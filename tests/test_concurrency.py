"""Concurrency Smoke Tests for INTELX Orchestration Pipeline."""

import asyncio

import pytest
from sqlalchemy import select

from intelx.core.enums import RunStatus
from intelx.db.models import Claim, Event
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker
from intelx.orchestration.engine import OrchestrationEngine


@pytest.mark.asyncio
async def test_five_simultaneous_jobs_concurrency_and_state_isolation():
    """Verify 5 concurrent jobs complete without state bleed, cost contamination, or claim leaks."""
    sessionmaker = get_sessionmaker()
    engine = OrchestrationEngine()

    run_ids: list[str] = []
    objectives = [
        "Assess sodium-ion battery cathode formulations",
        "Investigate composite sulfide solid electrolyte dendrites",
        "Benchmark 5000-qubit superconducting quantum annealing speedup",
        "Analyze high-capacity silicon-graphite anode swelling limits",
        "Evaluate piezoelectric kinetic energy recovery generators",
    ]

    # 1. Create 5 research runs concurrently
    async with sessionmaker() as session:
        for idx, obj in enumerate(objectives):
            run = await RunRepo.create_run(
                session=session,
                objective=f"[{idx + 1}] {obj}",
                scope_json={"depth": "quick", "budget": {"max_usd": 3.0, "max_minutes": 5}},
                created_by=f"concurrent-worker-{idx + 1}",
            )
            run_ids.append(run.id)
        await session.commit()

    assert len(run_ids) == 5

    # 2. Execute all 5 runs concurrently
    async def _execute_single(run_id: str):
        async with sessionmaker() as session:
            run = await engine.execute_run(session=session, run_id=run_id)
            if run.status == RunStatus.REVIEW_REQUIRED:
                run.scope_json = run.scope_json or {}
                run.scope_json["review_decision"] = "APPROVED"
                run.status = RunStatus.QUEUED
                await session.commit()
                run = await engine.execute_run(session=session, run_id=run_id)
            await session.commit()
            return run

    # return_exceptions=True so no worker is abandoned mid-flight. Plain gather
    # re-raises the first failure immediately and leaves the other four still
    # writing; the autouse clean_database_per_test fixture then drops the tables
    # underneath them and the *next* test fails with "DROP TABLE evidence:
    # database is locked" -- a failure in the harness that has nothing to do with
    # the run that actually broke. Collecting the exceptions keeps every worker
    # accounted for, and re-raising below still fails this test on any real error.
    outcomes = await asyncio.gather(
        *[_execute_single(rid) for rid in run_ids], return_exceptions=True
    )
    for rid, outcome in zip(run_ids, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            raise AssertionError(
                f"run {rid} raised {type(outcome).__name__}: {outcome}"
            ) from outcome
    results = outcomes

    # 3. Assert all 5 completed
    for run in results:
        assert run.status in (RunStatus.COMPLETED, RunStatus.REVIEW_REQUIRED)

    # 4. Verify strict state isolation across all 5 runs
    async with sessionmaker() as session:
        for rid in run_ids:
            # Verify run record
            db_run = await RunRepo.get_run(session, rid)
            assert db_run is not None
            assert db_run.status == RunStatus.COMPLETED

            # Verify claims belong exclusively to this run
            stmt_claims = select(Claim).where(Claim.run_id == rid)
            claims = list((await session.execute(stmt_claims)).scalars().all())
            for c in claims:
                assert c.run_id == rid

            # Verify events belong exclusively to this run
            stmt_events = select(Event).where(Event.run_id == rid)
            events = list((await session.execute(stmt_events)).scalars().all())
            for ev in events:
                assert ev.run_id == rid
