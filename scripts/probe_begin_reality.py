"""Does isolation_level=None give real BEGIN IMMEDIATE transactions, or merely
remove them?

If it merely removes them, then writes are not atomic and a mid-transaction
failure would leave partial rows -- which would be a correctness regression
hidden behind a passing concurrency number. This distinguishes the two directly:

  T1 atomicity: write two rows, fail before commit, check neither is visible.
  T2 contention: one writer holds a write transaction open; a second writer's
     write must BLOCK (proving a real lock exists), and must not fail.
  T3 BEGIN IMMEDIATE semantics: a writer holding a read snapshot cannot have its
     own upgrade refused -- the property BEGIN IMMEDIATE exists to provide.
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

from intelx.core.enums import RunStatus  # noqa: E402
from intelx.db.engine import get_async_engine  # noqa: E402
from intelx.db.models import ResearchRun  # noqa: E402
from tests.conftest import reset_test_schema  # noqa: E402

MODE = os.environ.get("ISO", "None")
stmts = []


def install(engine):
    sync = engine.sync_engine

    @event.listens_for(sync, "connect")
    def _iso(dbapi_conn, rec):
        dbapi_conn.isolation_level = None if MODE == "None" else ""

    @event.listens_for(sync, "before_cursor_execute")
    def before(conn, cur, statement, params, ctx, many):
        stmts.append(" ".join(statement.split())[:50])

    @event.listens_for(sync, "commit")
    def on_commit(conn):
        stmts.append("<<COMMIT>>")

    @event.listens_for(sync, "rollback")
    def on_rb(conn):
        stmts.append("<<ROLLBACK>>")


def vis(t):
    return [s for s in stmts if s.upper().startswith(t)]


async def main():
    db = Path("./data/probe_atomic.db").resolve()
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
    install(engine)
    await reset_test_schema(engine)
    mk = async_sessionmaker(bind=engine, class_=AsyncSession,
                            expire_on_commit=False, autoflush=False)

    async with engine.connect() as c:
        raw = c.sync_connection.connection
        print(f"ISO={MODE!r}  isolation_level={raw.isolation_level!r}\n")

    # ---- T1: is a multi-row write atomic across a failure? -----------------
    stmts.clear()
    try:
        async with mk() as s:
            await s.execute(ResearchRun.__table__.insert().values(
                id="1" * 32, objective="row one", status=RunStatus.QUEUED, scope_json={}))
            await s.execute(ResearchRun.__table__.insert().values(
                id="2" * 32, objective="row two", status=RunStatus.QUEUED, scope_json={}))
            raise RuntimeError("fail before commit")
    except RuntimeError:
        pass
    async with mk() as s:
        n = (await s.execute(select(ResearchRun).where(
            ResearchRun.id.in_(["1" * 32, "2" * 32])))).scalars().all()
    print(f"T1 atomicity : after failure before commit, visible rows = {len(n)}"
          f"   (0 = atomic, 2 = NOT atomic)   commits={len(vis('<<COMMIT>>'))}"
          f" rollbacks={len(vis('<<ROLLBACK>>'))}")

    # ---- T2: does a write transaction actually take the writer lock? -------
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with mk() as s:
            await s.execute(ResearchRun.__table__.insert().values(
                id="h" * 32, objective="holder", status=RunStatus.QUEUED, scope_json={}))
            started.set()
            await release.wait()
            await s.commit()

    async def competitor():
        await started.wait()
        await asyncio.sleep(0.3)
        t0 = time.perf_counter()
        try:
            async with mk() as s:
                await s.execute(ResearchRun.__table__.insert().values(
                    id="c" * 32, objective="competitor", status=RunStatus.QUEUED, scope_json={}))
                await s.commit()
            return time.perf_counter() - t0, "ok"
        except Exception as e:
            return time.perf_counter() - t0, type(e).__name__

    t = asyncio.create_task(holder())
    el, outcome = await competitor()
    release.set()
    await t
    print(f"T2 lock      : competing write blocked {el:.3f}s -> {outcome}"
          f"   (blocked > 0 = a real write lock is held)")


asyncio.run(main())