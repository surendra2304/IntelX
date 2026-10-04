"""Adversarial checks for the writer-lock boundary that execute_run now uses.

``release_writer_lock`` commits partway through a run, which splits what used to
be a single transaction into several. These drive the real engine and assert the
consequences that matter: the state machine still reaches a terminal, persisted
status; concurrent runs stay isolated; and no write transaction is left open
across the boundary.
"""

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from intelx.core.enums import RunStatus
from intelx.core.settings import get_settings
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker

TEST_DB = (Path(get_settings().DB_URL.split("///")[-1])).resolve()


@pytest_asyncio.fixture
async def session():
    sm = get_sessionmaker()
    async with sm() as s:
        yield s


async def _fresh_run(session, objective: str = "writer lock lifecycle probe") -> str:
    run = await RunRepo.create_run(
        session=session,
        objective=objective,
        scope_json={"domain": "science", "depth": "standard"},
    )
    await session.commit()
    return run.id


@pytest.mark.asyncio
async def test_status_survives_the_commit_and_refresh(session, monkeypatch):
    """The transition the boundary is meant to persist must not be discarded.

    ``refresh()`` overwrites in-memory attributes from the row, so if the status
    change had not been flushed before the commit the run would silently revert.
    """
    from intelx.db.session import release_writer_lock

    run_id = await _fresh_run(session)
    run = await RunRepo.get_run(session, run_id)
    run.status = RunStatus.SYNTHESIZING
    await session.flush()

    returned = await release_writer_lock(session, run)

    assert returned.status == RunStatus.SYNTHESIZING, (
        "release_writer_lock discarded the status transition it was called to persist"
    )

    async with get_sessionmaker()() as verify:
        stored = await RunRepo.get_run(verify, run_id)
        assert stored.status == RunStatus.SYNTHESIZING


@pytest.mark.asyncio
async def test_mid_pipeline_failure_still_reaches_a_persisted_terminal_state(session, monkeypatch):
    """Splitting one transaction into many must not strand a run mid-pipeline."""
    from intelx.orchestration import engine as engine_mod

    engine = engine_mod.OrchestrationEngine()

    async def boom(*args, **kwargs):
        raise RuntimeError("agent exploded mid-pipeline")

    # Fail after the planner boundary has already committed.
    monkeypatch.setattr(engine.planner, "execute", boom)
    monkeypatch.setattr(
        engine, "_check_gates", lambda *a, **k: _raise_after_first_gate()
    )

    async def _raise_after_first_gate():
        raise RuntimeError("gate blew up")

    run_id = await _fresh_run(session, "fails after a committed boundary")

    result = await engine.execute_run(session=session, run_id=run_id)

    assert result.status == RunStatus.FAILED, (
        f"run left in {result.status} after a mid-pipeline failure"
    )

    await session.commit()

    async with get_sessionmaker()() as verify:
        stored = await RunRepo.get_run(verify, run_id)
        assert stored.status == RunStatus.FAILED, (
            f"run persisted as {stored.status}; a committed boundary must not leave "
            "an intermediate state behind after a later failure"
        )
        assert stored.completed_at is not None


@pytest.mark.asyncio
async def test_boundary_does_not_leave_a_write_transaction_open(session):
    """A competing writer must be served immediately after the boundary."""
    from intelx.db.session import release_writer_lock

    run_id = await _fresh_run(session)
    run = await RunRepo.get_run(session, run_id)
    run.status = RunStatus.SYNTHESIZING
    await session.flush()

    await release_writer_lock(session, run)

    # A separate connection stands in for a concurrent research submission.
    conn = sqlite3.connect(TEST_DB, timeout=5.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        started = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
        blocked = time.monotonic() - started
    finally:
        conn.close()

    assert blocked < 1.0, f"a competing writer was blocked {blocked:.2f}s after the boundary"


@pytest.mark.asyncio
async def test_two_runs_do_not_bleed_state_across_the_boundary(session):
    """Concurrent runs stay isolated through their own commit boundaries.

    Each run gets its own session, as the worker does, so the two boundaries run
    genuinely in parallel against one SQLite file.
    """
    from intelx.db.session import release_writer_lock

    a_id = await _fresh_run(session, "isolation A")
    b_id = await _fresh_run(session, "isolation B")

    sm = get_sessionmaker()

    async def move(run_id: str, status: RunStatus):
        async with sm() as own:
            run = await RunRepo.get_run(own, run_id)
            run.status = status
            await own.flush()
            return await release_writer_lock(own, run)

    a2, b2 = await asyncio.gather(
        move(a_id, RunStatus.SYNTHESIZING),
        move(b_id, RunStatus.RETRIEVING),
    )

    assert (a2.status, b2.status) == (RunStatus.SYNTHESIZING, RunStatus.RETRIEVING)
    assert a2.objective == "isolation A"
    assert b2.objective == "isolation B"

    async with sm() as verify:
        sa = await RunRepo.get_run(verify, a_id)
        sb = await RunRepo.get_run(verify, b_id)
        assert (sa.status, sb.status) == (RunStatus.SYNTHESIZING, RunStatus.RETRIEVING)
        assert sa.objective == "isolation A"
        assert sb.objective == "isolation B"


# ── Every slow call must release the writer lock first ────────────────────────
#
# Mock mode runs the whole DAG in ~0.4s, so the suite cannot see contention on its
# own. These inject a delay into one stage at a time and have a competing
# connection attempt a write *during* that delay, using a long busy_timeout so the
# block time is the measurement. An earlier version sampled with a short
# timeout and could not distinguish a free lock from a held one -- it reported
# "released" for stages that were holding the lock for 30s.

STAGES = (
    "planner", "scout", "retriever", "extractor",
    "verifier", "analyst", "critic", "synthesizer",
)
SLOW_SECONDS = 1.0


def _competing_write(db_path, timeout: float = 30.0) -> float:
    """Seconds a competing writer is blocked; ~0 means the lock was free."""
    conn = sqlite3.connect(db_path, timeout=timeout, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
    t0 = time.monotonic()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    return time.monotonic() - t0


# Scout, retriever and extractor used to sit in a loop that flushed a task row
# immediately before its slow call, which took SQLite's single writer lock and held
# it for the whole loop -- measured at 32s for the scout and retriever and 33s
# across a seven-document extract batch. They no longer do: the engine leaves those
# rows pending for the next stage boundary, the retriever fetches every candidate
# before it ingests any of them, and the extractor runs every model call in the
# batch before it persists any of them. All of that adds no write transactions, so
# every stage is now held to the same bound with no exemption.


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", STAGES)
async def test_stage_does_not_hold_the_writer_lock(monkeypatch, stage, session):
    """No stage may hold SQLite's single writer lock across a slow call.

    Every agent in the DAG calls out to a model gateway or the web. SQLite permits
    one writer, so a transaction left open across one of those blocks every other
    writer -- including concurrent research submissions -- for the whole call.
    That is what produced the minute-long stalls and "database is locked" 500s.
    """
    import threading

    from intelx.orchestration.engine import OrchestrationEngine

    engine = OrchestrationEngine()
    agent = getattr(engine, stage)
    # The engine calls the extractor in one batch, so the slow call to probe is the
    # batch entry point rather than the single-document wrapper.
    method = "execute_many" if stage == "extractor" else "execute"
    original = getattr(agent, method)
    measured: list[float] = []

    async def slow_execute(*args, **kwargs):
        holder: list[float] = []

        def competitor():
            holder.append(_competing_write(TEST_DB))

        th = threading.Thread(target=competitor, daemon=True)
        th.start()
        await asyncio.sleep(SLOW_SECONDS)
        th.join(timeout=45)
        measured.extend(holder)
        return await original(*args, **kwargs)

    monkeypatch.setattr(agent, method, slow_execute)
    run_id = await _fresh_run(session, f"lock hold probe {stage}")

    async with get_sessionmaker()() as s:
        try:
            await engine.execute_run(session=s, run_id=run_id)
            await s.commit()
        except Exception:
            await s.rollback()

    assert measured, f"{stage} never ran"
    assert max(measured) < 0.5, (
        f"the {stage} stage held SQLite's writer lock for {max(measured):.2f}s while "
        "doing slow work; a competing submission would wait that long"
    )


@pytest.mark.asyncio
async def test_ecosystem_dispatch_does_not_hold_the_writer_lock(monkeypatch, session):
    """Delivery to peers is external HTTP; the lock must not span it."""
    import intelx.orchestration.engine as engine_mod
    import threading

    measured: list[float] = []

    async def slow_dispatch(**kwargs):
        holder: list[float] = []

        def competitor():
            holder.append(_competing_write(TEST_DB))

        th = threading.Thread(target=competitor, daemon=True)
        th.start()
        await asyncio.sleep(2.0)
        th.join(timeout=45)
        measured.extend(holder)
        return {"futuris": {"status": "skipped"}, "stratex": {"status": "skipped"}}

    monkeypatch.setattr(engine_mod, "_dispatch_external_research", slow_dispatch)
    engine = engine_mod.OrchestrationEngine()
    run_id = await _fresh_run(session, "dispatch lock probe")

    async with get_sessionmaker()() as s:
        try:
            await engine.execute_run(session=s, run_id=run_id)
            await s.commit()
        except Exception:
            await s.rollback()

    if not measured:
        return  # the fixture produced no ANSWERED run, so no dispatch to measure
    assert measured[0] < 0.5, (
        f"the ecosystem dispatch held the writer lock for {measured[0]:.2f}s; with a "
        "degraded peer its 15s budget becomes a 15s stall for every other writer"
    )
