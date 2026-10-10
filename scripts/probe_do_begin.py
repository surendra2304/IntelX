"""Does do_begin actually fire, and does BEGIN IMMEDIATE reach the driver?

The feasibility probe showed no BEGIN statement for an explicit begin() on an
autobegin=False session. Either do_begin is never called on that path, or the
statement is not visible through before_cursor_execute. This decides whether the
whole design is viable, so it is measured directly at the driver: a trace
callback on the raw DBAPI connection sees every statement including ones
SQLAlchemy emits outside its own event hooks.

Four arms:
  A  autobegin=True  + implicit write (today's behaviour)
  B  autobegin=False + explicit begin(), DEFERRED opener
  C  autobegin=False + explicit begin(), IMMEDIATE opener
  D  autobegin=False + SELECT then explicit begin()   (read must not block begin)
"""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

os.environ["INTELX_ENV"] = "testing"
os.environ["INTELX_MOCK_MODE"] = "true"
sys.path.insert(0, str(Path(".").resolve()))

from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from intelx.core.enums import RunStatus  # noqa: E402
from intelx.db.engine import get_async_engine  # noqa: E402
from intelx.db.models import ResearchRun  # noqa: E402
from tests.conftest import reset_test_schema  # noqa: E402

seen = []


def install_driver_trace(engine):
    """Trace statements SQLAlchemy emits, including the transaction opener."""
    sync = engine.sync_engine

    @event.listens_for(sync, "before_cursor_execute")
    def on_exec(conn, cur, statement, params, ctx, many):
        seen.append(" ".join(statement.split())[:60])

    @event.listens_for(sync, "begin")
    def on_begin(conn):
        seen.append("<<sqlalchemy.begin event>>")

    @event.listens_for(sync, "commit")
    def on_commit(conn):
        seen.append("<<commit>>")


def opener(mode):
    if mode == "IMMEDIATE":
        return lambda c: c.execute("BEGIN IMMEDIATE")
    return lambda c: c.execute("BEGIN")


async def main():
    db = Path("./data/probe_begin.db").resolve()
    url = f"sqlite+aiosqlite:///{db.as_posix()}"
    os.environ["INTELX_DB_URL"] = url
    engine = get_async_engine(url)
    install_driver_trace(engine)
    await reset_test_schema(engine)

    mk = async_sessionmaker(bind=engine, class_=AsyncSession,
                            expire_on_commit=False, autoflush=False)

    def mark():
        seen.clear()

    def show(label):
        begins = [s for s in seen
                  if s.upper().startswith("BEGIN") or "begin event" in s]
        print(f"  {label:<44} opener: {begins if begins else 'NONE'}")

    # Arm A: today's behaviour
    mark()
    async with mk() as s:
        await s.execute(select(ResearchRun).limit(1))
        await s.execute(ResearchRun.__table__.insert().values(
            id="a" * 32, objective="A", status=RunStatus.QUEUED, scope_json={}))
        await s.commit()
    show("A autobegin=True + implicit write")

    # Arm B/C: explicit begin on a transactionless session
    for mode in ("DEFERRED", "IMMEDIATE"):
        engine.sync_engine.dialect.do_begin = opener(mode)
        mark()
        async with mk() as s:
            s.autobegin = False
            async with s.begin():
                await s.execute(ResearchRun.__table__.insert().values(
                    id=("b" if mode == "DEFERRED" else "c") * 32,
                    objective=mode, status=RunStatus.QUEUED, scope_json={}))
        show(f"{'B' if mode == 'DEFERRED' else 'C'} autobegin=False + begin() {mode}")

    # Arm D: a read first, then an explicit write
    engine.sync_engine.dialect.do_begin = opener("IMMEDIATE")
    mark()
    async with mk() as s:
        s.autobegin = False
        await s.execute(select(ResearchRun).limit(1))
        try:
            async with s.begin():
                await s.execute(ResearchRun.__table__.insert().values(
                    id="d" * 32, objective="D", status=RunStatus.QUEUED, scope_json={}))
            show("D SELECT then begin() IMMEDIATE")
        except Exception as e:
            show("D SELECT then begin() IMMEDIATE")
            print(f"     raised: {type(e).__name__}: {e}")

    # Does a read-only session leave any transaction open?
    mark()
    async with mk() as s:
        s.autobegin = False
        await s.execute(select(ResearchRun).limit(1))
        print(f"  read-only session in_transaction(): {s.in_transaction()}")
    show("read-only session (autobegin=False)")


asyncio.run(main())