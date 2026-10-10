"""Can a read-only transaction be told apart from a write one, at begin time?

The conflict is exact:
  - every transaction IMMEDIATE  -> 8/8 concurrent runs, but a second writer is
    blocked 3.41s during synthesis (read-only stages take the writer lock)
  - every transaction deferred   -> readers never take the writer lock, but
    read-then-write transactions fail their upgrade (3/8 concurrent runs)

So IMMEDIATE must apply to write transactions only. SQLAlchemy chooses the
opener before the first statement runs, so the question is whether anything is
knowable at that point.

Tested here:
  1. Does the ORM expose which objects are dirty before the first flush?
  2. Does an explicit write (Core insert on a session) differ observably from a
     read-only one at begin time?
  3. Does session.no_autoflush + pending adds stay pending, so a transaction
     opened before a later write can be classified at flush time instead?
"""

import asyncio
import os
import sys
from pathlib import Path

os.environ["INTELX_ENV"] = "testing"
os.environ["INTELX_MOCK_MODE"] = "true"
sys.path.insert(0, str(Path(".").resolve()))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from intelx.core.enums import RunStatus  # noqa: E402
from intelx.db.engine import get_async_engine  # noqa: E402
from intelx.db.models import ResearchRun, Task  # noqa: E402
from tests.conftest import reset_test_schema  # noqa: E402


async def main():
    db = Path("./data/probe_classify.db").resolve()
    url = f"sqlite+aiosqlite:///{db.as_posix()}"
    os.environ["INTELX_DB_URL"] = url
    engine = get_async_engine(url)
    await reset_test_schema(engine)
    mk = async_sessionmaker(bind=engine, class_=AsyncSession,
                            expire_on_commit=False, autoflush=False)

    # 1. What is observable at begin time?
    async with mk() as s:
        print("1. at session start:")
        print(f"   new={s.new} dirty={s.dirty} deleted={s.deleted}")

    # Parent run so Task's FK is satisfied.
    async with mk() as s:
        s.add(ResearchRun(id="a" * 32, objective="parent", status=RunStatus.QUEUED,
                          scope_json={}))
        await s.commit()

    # 2. Pending ORM adds that a later flush will write -- the pipeline's shape.
    async with mk() as s:
        s.add(Task(run_id="a" * 32, type="scout", status="RUNNING", payload_json={}))
        print("\n2. after session.add(Task), before flush:")
        print(f"   new={len(s.new)}  (visible at begin time: {len(s.new) > 0})")
        await s.commit()

    # 3. After a read, is a pending add still pending, or already flushed?
    async with mk() as s:
        s.add(Task(run_id="a" * 32, type="scout", status="RUNNING", payload_json={}))
        await s.execute(select(ResearchRun).limit(1))
        print("\n3. after add + read:")
        print(f"   new={len(s.new)}  (still pending: {len(s.new) > 0})")
        await s.commit()

    # 4. Can a read-only transaction be told apart at the moment BEGIN is emitted?
    #    Hook do_begin and inspect the session state SQLAlchemy will hand it.
    seen = []

    def probe_begin(dbapi_connection):
        seen.append("BEGIN requested")

    engine.sync_engine.dialect.do_begin = probe_begin

    async with mk() as s:
        await s.execute(select(ResearchRun).limit(1))
        print(f"\n4. read-only session: begins={len(seen)} new={len(s.new)} "
              f"dirty={len(s.dirty)} in_transaction={s.in_transaction()}")

    seen.clear()
    async with mk() as s:
        s.autoflush = False
        s.add(Task(run_id="a" * 32, type="scout", status="RUNNING", payload_json={}))
        await s.execute(select(ResearchRun).limit(1))
        print(f"   read-then-write session: begins={len(seen)} new={len(s.new)} "
              f"(new>0 at read time: {len(s.new) > 0})")
        await s.commit()

    # 5. THE decisive one: a Core UPDATE -- which the engine uses for every run
    #    status transition -- leaves session.new empty. Is it distinguishable?
    seen.clear()
    async with mk() as s:
        s.autoflush = False
        await s.execute(select(ResearchRun).limit(1))
        print("\n5. read then Core UPDATE:")
        print(f"   after read: new={len(s.new)} dirty={len(s.dirty)} "
              f"in_transaction={s.in_transaction()}")
        await s.execute(ResearchRun.__table__.update()
                        .where(ResearchRun.id == "a" * 32)
                        .values(status=RunStatus.PLANNING))
        print(f"   after Core UPDATE: new={len(s.new)} dirty={len(s.dirty)} "
              f"-> Core writes are INVISIBLE to session.new/dirty")
        await s.commit()


asyncio.run(main())