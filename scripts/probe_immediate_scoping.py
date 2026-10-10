"""Can BEGIN IMMEDIATE be scoped to genuine write phases?

The two requirements are in direct conflict, and both are now measured:

  every txn IMMEDIATE   -> 8/8 concurrent runs, but a second writer blocked
                           3.41s during synthesis (read-only stages take the
                           writer lock), failing 12 lock-guard tests
  every txn deferred    -> readers never take the writer lock, but read-then-write
                           transactions fail their snapshot upgrade (3/8 runs)

So IMMEDIATE must apply to write transactions only. A ContextVar set around a
write block looks like the answer, but do_begin is invoked through aiosqlite's
greenlet bridge onto a worker thread, so whether the ContextVar is even visible
there is unproven. That is the decisive question, and it is what this measures.

Arms:
  A  no contextvar, every txn deferred        (today)
  B  no contextvar, every txn IMMEDIATE
  C  ContextVar set only inside the write block
"""

import asyncio
import os
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

os.environ["INTELX_ENV"] = "testing"
os.environ["INTELX_MOCK_MODE"] = "true"
sys.path.insert(0, str(Path(".").resolve()))

from sqlalchemy import event, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from intelx.core.enums import RunStatus  # noqa: E402
from intelx.db.engine import get_async_engine  # noqa: E402
from intelx.db.models import ResearchRun  # noqa: E402
from tests.conftest import reset_test_schema  # noqa: E402

ARM = os.environ.get("ARM", "C")
_in_write: ContextVar[bool] = ContextVar("in_write", default=False)
opened = []


@contextmanager
def write_block():
    t = _in_write.set(True)
    try:
        yield
    finally:
        _in_write.reset(t)


def do_begin(dbapi_connection):
    flag = _in_write.get()
    stmt = "BEGIN IMMEDIATE" if flag else "BEGIN"
    opened.append(stmt)
    dbapi_connection.execute(stmt)


async def main():
    db = Path("./data/probe_scope.db").resolve()
    url = f"sqlite+aiosqlite:///{db.as_posix()}"
    os.environ["INTELX_DB_URL"] = url
    for suf in ("", "-wal", "-shm"):
        f = Path(str(db) + suf)
        if f.exists():
            try:
                f.unlink()
            except OSError:
                pass
    engine = get_async_engine(url)
    sync = engine.sync_engine
    sync.dialect.do_begin = do_begin
    if ARM == "B":
        _in_write.set(True)          # every transaction is a write
    await reset_test_schema(engine)
    mk = async_sessionmaker(bind=engine, class_=AsyncSession,
                            expire_on_commit=False, autoflush=False)

    # The ContextVar is set in the coroutine; do_begin runs on the aiosqlite
    # worker thread. If the flag arrives here, C can work.
    opened.clear()
    async with mk() as s:
        with write_block():
            await s.execute(ResearchRun.__table__.insert().values(
                id="a" * 32, objective="in write block", status=RunStatus.QUEUED,
                scope_json={}))
            await s.commit()
    print(f"  write block opened: {opened}")

    opened.clear()
    async with mk() as s:
        await s.execute(select(ResearchRun).limit(1))
        await s.commit()
    print(f"  read-only opened:  {opened}")
    print(f"  ContextVar visible in do_begin: "
          f"{'BEGIN IMMEDIATE' in opened if ARM == 'C' else 'n/a'}")


asyncio.run(main())