"""Feasibility probe for the read/write session split.

Three questions, answered empirically rather than assumed:

1. With autobegin=False, does a SELECT open a transaction at all? (It must not,
   or reads still pin a WAL snapshot and can still block the next write.)
2. Does an explicit write transaction emit BEGIN IMMEDIATE and commit?
3. INVARIANT 1: does a separate autocommit read connection see writes that the
   write connection has already committed? A run's reads must see the run's own
   preceding writes.
4. INVARIANT 2: do two workers on separate connections stay isolated?
"""

import asyncio
import os
import sys
import time
from pathlib import Path

os.environ["INTELX_ENV"] = "testing"
os.environ["INTELX_MOCK_MODE"] = "true"
sys.path.insert(0, str(Path(".").resolve()))

from sqlalchemy import event, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from intelx.db.engine import get_async_engine  # noqa: E402
from intelx.db.base import Base  # noqa: E402
from intelx.db.models import ResearchRun  # noqa: E402
from intelx.core.enums import RunStatus  # noqa: E402
from tests.conftest import reset_test_schema  # noqa: E402

log = []
BEGIN_MODE = os.environ.get("BEGIN_MODE", "IMMEDIATE")


def _begin(connection):
    """The opener every explicit transaction goes through."""
    if BEGIN_MODE == "IMMEDIATE":
        connection.execute("BEGIN IMMEDIATE")
    else:
        connection.execute("BEGIN")


def install(engine):
    sync = engine.sync_engine

    @event.listens_for(sync, "before_cursor_execute")
    def before(conn, cur, statement, parameters, context, executemany):
        head = " ".join(statement.split())
        log.append((time.perf_counter(), head[:70]))

    @event.listens_for(sync, "commit")
    def on_commit(conn):
        log.append((time.perf_counter(), "<<COMMIT>>"))

    @event.listens_for(sync, "rollback")
    def on_rollback(conn):
        log.append((time.perf_counter(), "<<ROLLBACK>>"))


def begins_in(since):
    return [s for _, s in log[since:] if s.upper().startswith("BEGIN")]


async def main():
    db = Path("./data/probe_split.db").resolve()
    url = f"sqlite+aiosqlite:///{db.as_posix()}"
    os.environ["INTELX_DB_URL"] = url
    engine = get_async_engine(url)
    install(engine)
    if BEGIN_MODE == "IMMEDIATE":
        engine.sync_engine.dialect.do_begin = _begin
    await reset_test_schema(engine)

    write_maker = async_sessionmaker(bind=engine, class_=AsyncSession,
                                     expire_on_commit=False, autoflush=False)
    read_maker = async_sessionmaker(bind=engine, class_=AsyncSession,
                                    expire_on_commit=False, autoflush=False)

    # ---- Q1/Q2: autobegin=False on the write session -----------------------
    async with write_maker() as w:
        w.autobegin = False
        mark = len(log)
        await w.execute(text("SELECT 1"))
        print(f"Q1 read-only SELECT issued BEGIN? {bool(begins_in(mark))}"
              f"   (autobegin=False)")

        mark = len(log)
        async with w.begin_nested():
            await w.execute(
                ResearchRun.__table__.insert().values(
                    id="a" * 32, objective="run A", status=RunStatus.QUEUED, scope_json={}))
        print(f"Q2a nested-BEGIN write BEGIN stmts: {begins_in(mark)}")

    # A fresh write session: autobegin=False means no implicit transaction, so an
    # explicit begin() is legal and is the only way a write transaction opens.
    async with write_maker() as w2:
        w2.autobegin = False
        mark = len(log)
        async with w2.begin():
            await w2.execute(
                ResearchRun.__table__.insert().values(
                    id="e" * 32, objective="run E", status=RunStatus.QUEUED, scope_json={}))
        print(f"Q2b fresh write session begin() BEGIN stmts: {begins_in(mark)}")

    # ---- Q3 INVARIANT 1: separate autocommit reader sees committed write ----
    async with read_maker() as r:
        r.autobegin = False
        mark = len(log)
        got = (await r.execute(
            select(ResearchRun.objective).where(ResearchRun.id == "a" * 32)
        )).scalar_one_or_none()
        print(f"INV1 separate reader sees committed write: {got!r}"
              f"   (reader opened BEGIN? {bool(begins_in(mark))})")

    # ---- Q4 INVARIANT 2: isolation across workers ---------------------------
    async def worker(tag, val):
        async with write_maker() as s:
            s.autobegin = False
            async with s.begin():
                await s.execute(ResearchRun.__table__.insert().values(
                    id=tag * 32, objective=val, status=RunStatus.QUEUED, scope_json={}))
        async with read_maker() as r:
            r.autobegin = False
            return (await r.execute(
                select(ResearchRun.objective).where(ResearchRun.id == tag * 32)
            )).scalar_one()

    seen = await asyncio.gather(worker("b", "belongs to b"), worker("c", "belongs to c"))
    print(f"INV2 each worker reads back only its own row: {seen}")

    # ---- Q5: does a read snapshot block a concurrent write? ----------------
    # Reader opens a long transaction by reading; writer tries to write.
    # With the split, the reader never opens one, so this should be the case
    # that used to fail.
    async def slow_reader():
        async with read_maker() as r:
            r.autobegin = False
            await r.execute(text("SELECT count(*) FROM research_runs"))
            await asyncio.sleep(1.0)

    async def competing_write():
        await asyncio.sleep(0.2)
        t0 = time.perf_counter()
        async with write_maker() as s:
            s.autobegin = False
            async with s.begin():
                await s.execute(ResearchRun.__table__.insert().values(
                    id="d" * 32, objective="competing", status=RunStatus.QUEUED, scope_json={}))
        return time.perf_counter() - t0

    el = await asyncio.gather(slow_reader(), competing_write())
    print(f"Q5 competing write blocked {el[1]:.3f}s while a reader slept 1.0s")

    print("\n--- statement log tail ---")
    for _, s in log[-18:]:
        print("   ", s)


asyncio.run(main())