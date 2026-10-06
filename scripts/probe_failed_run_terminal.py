"""Prove a failed run reaches FAILED with its reason recorded, through the real path.

Motivation. `OrchestrationEngine.execute_run` catches a stage failure and then calls
`await session.flush()` on the same session. When the failure came from the database
itself -- the measured `(sqlite3.OperationalError) database is locked` on
`INSERT INTO claims` -- SQLAlchemy has already deactivated that transaction, so the
handler's own flush raises `PendingRollbackError`. That escapes `execute_run`, the
caller never commits, and the run is left in whatever state it last reached: a
non-terminal run that nothing will ever pick up again.

This probe drives `execute_run` directly, exactly as `tests/test_concurrency.py` and
the API callers do, and reports what the database says afterwards.

    python scripts/probe_failed_run_terminal.py

Exit code 0 means both scenarios reached FAILED with a recorded reason.
"""

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

TEST_DB_PATH = (REPO / "data" / "probe_failed_run.db").resolve()
os.environ["INTELX_ENV"] = "testing"
os.environ["INTELX_MOCK_MODE"] = "true"
os.environ["INTELX_DB_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["INTELX_MAX_CONCURRENT_RUNS"] = "5"

from intelx.core.enums import RunStatus  # noqa: E402
from intelx.db.engine import get_async_engine  # noqa: E402
from intelx.db.models import ResearchRun  # noqa: E402
from intelx.db.repos import RunRepo  # noqa: E402
from intelx.db.session import get_sessionmaker  # noqa: E402
from intelx.orchestration.engine import OrchestrationEngine  # noqa: E402
from tests.conftest import reset_test_schema  # noqa: E402

TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


async def _fresh_run(sessionmaker, label: str) -> str:
    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective=f"probe {label}",
            scope_json={"depth": "quick", "budget": {"max_usd": 3.0, "max_minutes": 5}},
            created_by="probe-failed-run",
        )
        await session.commit()
        return run.id


async def _read_back(sessionmaker, run_id: str):
    async with sessionmaker() as session:
        run = await RunRepo.get_run(session, run_id)
        if run is None:
            return None
        return {
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "outcome": run.outcome.value if run.outcome else None,
            "error_json": run.error_json,
            "completed_at": str(run.completed_at),
        }


async def _drive(engine, sessionmaker, run_id: str) -> dict:
    """Run execute_run the way a real caller does: execute, then commit."""
    raised: BaseException | None = None
    returned = None
    async with sessionmaker() as session:
        try:
            returned = await engine.execute_run(session=session, run_id=run_id)
            # What run_once(), the API path and the tests all do afterwards.
            await session.commit()
        except BaseException as exc:  # noqa: BLE001 - the point is to observe it
            raised = exc
    return {"raised": raised, "returned": returned}


async def _scenario(sessionmaker, label: str, inject) -> bool:
    run_id = await _fresh_run(sessionmaker, label)
    engine = OrchestrationEngine()
    inject(engine)

    outcome = await _drive(engine, sessionmaker, run_id)
    state = await _read_back(sessionmaker, run_id)

    print(f"\n--- {label} ---")
    if outcome["raised"] is not None:
        print(
            f"  execute_run raised : {type(outcome['raised']).__name__}: "
            f"{str(outcome['raised'])[:110]}"
        )
    else:
        got = outcome["returned"]
        print(
            f"  execute_run returned: status="
            f"{got.status.value if hasattr(got.status, 'value') else got.status}"
        )
    print(f"  persisted status    : {state['status'] if state else 'NO ROW'}")
    print(f"  persisted outcome   : {state['outcome'] if state else '-'}")
    print(f"  persisted reason    : {state['error_json'] if state else '-'}")
    print(f"  completed_at        : {state['completed_at'] if state else '-'}")

    if state is None:
        print("  VERDICT             : FAIL - run row missing")
        return False
    if state["status"] != RunStatus.FAILED.value:
        print(f"  VERDICT             : FAIL - stranded in {state['status']!r}, not terminal")
        return False
    if not state["error_json"]:
        print("  VERDICT             : FAIL - FAILED but no reason recorded")
        return False
    if not state["completed_at"] or state["completed_at"].startswith("None"):
        print("  VERDICT             : FAIL - FAILED but completed_at not set")
        return False
    if outcome["raised"] is not None:
        print(
            f"  VERDICT             : FAIL - persisted, but execute_run still raised "
            f"{type(outcome['raised']).__name__}"
        )
        return False
    print("  VERDICT             : PASS - terminal FAILED, reason recorded")
    return True


def _inject_stage_error(engine: OrchestrationEngine) -> None:
    """A stage raises a plain exception; the session itself is still usable."""

    async def boom(**kwargs):
        raise RuntimeError("forced stage failure")

    engine.planner.execute = boom


def _inject_database_error(engine: OrchestrationEngine) -> None:
    """A real DB error inside the try block, leaving the session deactivated.

    This is the production mechanism without the lock-timing dependence. It has to
    fail *during flush*: SQLAlchemy only deactivates the transaction when a flush
    raises, which is why an error from a bare `session.execute()` is not enough to
    reproduce it.
    """
    original = engine._check_gates
    state = {"fired": False}

    async def gates(session, run_id):
        if not state["fired"]:
            state["fired"] = True
            # ORM insert missing a NOT NULL column: fails inside flush(), exactly
            # where the measured `INSERT INTO claims ... database is locked` failed.
            session.add(ResearchRun(id="probe-violation", status=RunStatus.QUEUED))
            await session.flush()
        return await original(session, run_id)

    engine._check_gates = gates


async def main() -> int:
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        stale = Path(str(TEST_DB_PATH) + suffix)
        if stale.exists():
            try:
                stale.unlink()
            except PermissionError:
                pass

    engine = get_async_engine(os.environ["INTELX_DB_URL"])
    await reset_test_schema(engine)
    await engine.dispose()

    sessionmaker = get_sessionmaker()
    results = [
        await _scenario(sessionmaker, "stage raises RuntimeError", _inject_stage_error),
        await _scenario(sessionmaker, "database error inside the stage", _inject_database_error),
    ]
    await engine.dispose()

    ok = sum(results)
    print(f"\n==== {ok}/{len(results)} scenarios reached FAILED with a recorded reason ====")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
