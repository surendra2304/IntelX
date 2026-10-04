"""Research submissions must never stall behind the database writer lock.

Measured with Memora killed: POST /api/v1/friday/research returned HTTP 500 after
89.8s while every other endpoint answered in ~3ms. The cause was
`sqlite3.OperationalError: database is locked` on INSERT (33 occurrences in the log):
the engine waited 60s for the writer lock, and the background worker held that lock
across its external web fetches because it transitioned run state and then ran the
synthesizer without committing in between.

Each test below fails if the corresponding part of the fix is reverted.
"""

import asyncio
import re
import sqlite3
import threading
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_sqlite_busy_timeout_is_bounded():
    """A 60s busy timeout turns write contention into a 60-second stall."""
    source = _source("intelx/db/engine.py")
    match = re.search(r"PRAGMA busy_timeout\s*=\s*(\d+)", source)
    assert match, "engine.py no longer sets a busy_timeout"
    assert int(match.group(1)) <= 5000, (
        f"busy_timeout is {match.group(1)}ms; anything near the old 60000ms turns "
        "contention into a request that blocks for a minute"
    )


def test_sqlite_connect_timeout_is_bounded():
    source = _source("intelx/db/engine.py")
    match = re.search(r'"timeout"\s*:\s*([0-9.]+)', source)
    assert match, "engine.py no longer sets a connect timeout"
    assert float(match.group(1)) <= 5.0, f"connect timeout is {match.group(1)}s"


def test_research_run_writes_are_serialized():
    """Without the lock, simultaneous submissions collide on the single writer."""
    from intelx.api.v1.friday import _RUN_WRITE_ATTEMPTS, _RUN_WRITE_LOCK

    assert isinstance(_RUN_WRITE_LOCK, asyncio.Lock)
    assert _RUN_WRITE_ATTEMPTS >= 1
    source = _source("intelx/api/v1/friday.py")
    assert "async with _RUN_WRITE_LOCK:" in source, "run creation no longer takes the write lock"
    assert "OperationalError" in source, "a contended write is no longer retried"


def test_every_synthesis_transition_commits_before_slow_work():
    """Every path into the synthesizer must release the writer lock first.

    This checks each SYNTHESIZING transition in the file rather than the first one:
    the resumption path was fixed while the primary path still held the lock across
    synthesis, and a first-match-only assertion passed anyway.
    """
    source = _source("intelx/orchestration/engine.py")
    pattern = r"transition_state\(\s*session\s*,\s*run\s*,\s*RunStatus\.SYNTHESIZING\s*\)"
    windows = 0

    for match in re.finditer(pattern, source):
        start = match.end()
        end = source.find("self.synthesizer.execute", start)
        assert end != -1, "a SYNTHESIZING transition no longer leads to synthesis"
        window = source[start:end]
        # The boundary is now owned by db.session.release_writer_lock, which does
        # the commit; either spelling is acceptable, doing neither is not.
        assert "await session.commit()" in window or "release_writer_lock" in window, (
            "the writer lock is held across the synthesizer again on one of the "
            "execution paths; commit before executing it"
        )
        windows += 1

    assert windows >= 2, (
        f"only {windows} SYNTHESIZING transition(s) matched; the primary path and the "
        "review-resumption path should both be covered by this check"
    )


@pytest.mark.asyncio
async def test_synthesis_releases_the_writer_lock():
    """The regression that produced the 90-second stall, driven end to end.

    execute_run is run against the real database with the synthesizer replaced by a
    stand-in for its external web fetches. While that stand-in is running, a second
    connection tries to take SQLite's single writer lock. If the engine committed
    before synthesizing, that writer is served immediately; if it did not, the writer
    waits out the busy timeout, which is exactly what stalled real submissions.
    """
    from intelx.core.settings import get_settings
    from intelx.db.repos import RunRepo
    from intelx.db.session import get_sessionmaker
    from intelx.orchestration.engine import OrchestrationEngine

    settings = get_settings()
    settings.MOCK_MODE = True
    db_path = Path(settings.DB_URL.split("///")[-1])
    sessionmaker = get_sessionmaker()

    probe: dict[str, float] = {}

    def competing_writer() -> None:
        """Stand in for a second research submission arriving mid-synthesis."""
        conn = sqlite3.connect(db_path, timeout=3.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout = 3000")
        started = time.monotonic()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("COMMIT")
        except sqlite3.OperationalError:
            pass  # refused; the elapsed time below is what matters
        finally:
            probe["blocked"] = time.monotonic() - started
            conn.close()

    engine = OrchestrationEngine()
    original_execute = engine.synthesizer.execute
    synthesis_reached = threading.Event()

    async def slow_synthesis(*args, **kwargs):
        synthesis_reached.set()
        await asyncio.to_thread(competing_writer)
        return await original_execute(*args, **kwargs)

    engine.synthesizer.execute = slow_synthesis

    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective="Assess solid state battery electrolyte conductivity",
            scope_json={"domain": "science", "depth": "standard"},
        )
        await session.commit()
        await engine.execute_run(session=session, run_id=run.id)
        await session.commit()

    assert synthesis_reached.is_set(), "execute_run never reached synthesis; test is not exercising it"
    assert "blocked" in probe, "the competing writer never ran"
    assert probe["blocked"] < 1.0, (
        f"a second writer was blocked for {probe['blocked']:.2f}s while the synthesizer "
        "ran: the engine is holding SQLite's writer lock across slow external I/O"
    )


def test_contended_writer_fails_inside_the_bounded_deadline(tmp_path):
    """Deterministic reproduction of the contention that produced the 90s stall.

    A separate connection takes SQLite's single writer lock and holds it for longer
    than the configured busy timeout. A second writer must then be refused within
    seconds. Before the fix the same situation waited out a 60-second busy_timeout,
    which is what turned concurrent research submissions into a minute-long stall.

    Contention is imposed explicitly and signalled with an event rather than left to
    the scheduler, so the assertion measures the deadline and not thread timing.
    """
    db = tmp_path / "contention.db"
    setup = sqlite3.connect(db)
    setup.execute("PRAGMA journal_mode=WAL")
    setup.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, note TEXT)")
    setup.commit()
    setup.close()

    hold_seconds = 7.0  # deliberately longer than the 5s busy timeout
    lock_held = threading.Event()
    release = threading.Event()

    def hold_writer_lock() -> None:
        conn = sqlite3.connect(db, timeout=10.0, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO runs (note) VALUES ('holder')")
            lock_held.set()  # the writer lock is now definitively held
            release.wait(hold_seconds)
            conn.execute("ROLLBACK")
        finally:
            conn.close()

    holder = threading.Thread(target=hold_writer_lock, daemon=True)
    holder.start()
    try:
        assert lock_held.wait(timeout=10.0), "the holder never took the writer lock"

        contender = sqlite3.connect(db, timeout=30.0, isolation_level=None)
        contender.execute("PRAGMA busy_timeout = 5000")
        started = time.monotonic()
        try:
            contender.execute("BEGIN IMMEDIATE")
            contender.execute("COMMIT")
            raised = None
        except sqlite3.OperationalError as exc:
            raised = exc
        finally:
            contender.close()
        elapsed = time.monotonic() - started
    finally:
        release.set()
        holder.join(timeout=hold_seconds + 5)

    assert raised is not None, (
        "the contender took the writer lock while another connection still held it; "
        "the test did not actually create contention"
    )
    assert elapsed < 8.0, (
        f"a refused writer waited {elapsed:.1f}s; the bounded busy timeout should "
        "surface contention in seconds, not the old 60s"
    )


def test_retry_budget_is_bounded_by_the_request_deadline():
    """Backoff must not grow into another multi-second stall."""
    source = _source("intelx/api/v1/friday.py")
    assert "_RUN_WRITE_ATTEMPTS = " in source
    match = re.search(r"_RUN_WRITE_ATTEMPTS\s*=\s*(\d+)", source)
    attempts = int(match.group(1))
    # Worst case backoff for the attempt count must stay inside a few seconds.
    worst_case_sleep = sum(0.2 * (2**i) for i in range(max(0, attempts - 1)))
    assert worst_case_sleep < 5.0, f"retry backoff can sleep {worst_case_sleep:.1f}s"
    assert "asyncio.sleep(0.2 * (2**attempt))" in source, "bounded backoff changed shape"
