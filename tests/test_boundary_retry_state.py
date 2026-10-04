"""Does the boundary retry silently drop the state it exists to persist?

release_writer_lock commits, and on OperationalError rolls back and retries. A
rollback discards everything uncommitted since the last successful commit -- which
at a stage boundary is the state transition and its events. If that loss is
silent, the run keeps executing while the database says it is somewhere else.
"""

import pytest
import pytest_asyncio
from sqlalchemy.exc import OperationalError

from intelx.core.enums import RunStatus
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker, release_writer_lock


@pytest_asyncio.fixture
async def session():
    sm = get_sessionmaker()
    async with sm() as s:
        yield s


async def _fresh(session, objective: str) -> str:
    run = await RunRepo.create_run(
        session=session, objective=objective, scope_json={"depth": "standard"}
    )
    await session.commit()
    return run.id


@pytest.mark.asyncio
async def test_transition_survives_a_failed_boundary_commit(session, monkeypatch):
    """A retried commit must not lose the transition it was called to persist."""
    run_id = await _fresh(session, "retry must not lose state")
    run = await RunRepo.get_run(session, run_id)
    run.status = RunStatus.SYNTHESIZING
    await session.flush()

    real_commit = session.commit
    calls = {"n": 0}

    async def flaky_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate SQLite refusing the writer lock for the first attempt.
            raise OperationalError(None, None, Exception("database is locked"))
        return await real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)

    returned = await release_writer_lock(session, run)

    monkeypatch.undo()
    assert calls["n"] == 2, "the commit should have been retried once"

    async with get_sessionmaker()() as verify:
        stored = await RunRepo.get_run(verify, run_id)
        print(
            f"\n  after a failed-then-retried boundary commit: "
            f"in-memory={returned.status} persisted={stored.status}"
        )
        assert stored.status == RunStatus.SYNTHESIZING, (
            f"the boundary dropped the transition: persisted {stored.status}, "
            "expected SYNTHESIZING. The retry rolled back the state it was "
            "protecting and continued silently."
        )
