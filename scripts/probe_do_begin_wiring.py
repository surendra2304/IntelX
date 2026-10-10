"""Does overriding do_begin actually produce BEGIN IMMEDIATE end to end?

Earlier probes reported no BEGIN for the override, which was set on the dialect
instance after a transaction had already been opened. do_begin is called from
Connection._begin_impl on every transaction, and the SQLite dialect defines it as
pass -- so a class-level override should fire. This verifies it reaches the driver
by checking pysqlite's own view of the transaction, which is authoritative and
does not depend on SQLAlchemy's statement events.

An explicit BEGIN IMMEDIATE only works if pysqlite is in isolation_level=None
mode (otherwise it prepends its own BEGIN). So this also tests the combination
that is actually required.
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

MODE = os.environ.get("MODE", "override_iso")   # override | override_iso | plain_iso


def do_begin_immediate(dbapi_connection):
    dbapi_connection.execute("BEGIN IMMEDIATE")


async def main():
    db = Path("./data/probe_wire.db").resolve()
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

    if MODE in ("override_iso", "plain_iso"):
        @event.listens_for(sync, "connect")
        def _iso(dbapi_conn, rec):
            dbapi_conn.isolation_level = None

    if MODE in ("override", "override_iso"):
        sync.dialect.do_begin = do_begin_immediate

    await reset_test_schema(engine)
    mk = async_sessionmaker(bind=engine, class_=AsyncSession,
                            expire_on_commit=False, autoflush=False)

    async with engine.connect() as c:
        raw = c.sync_connection.connection
        print(f"MODE={MODE:<14} isolation_level={raw.isolation_level!r}  "
              f"do_begin={sync.dialect.do_begin.__name__}")

    # A read-then-write, the shape that fails. If BEGIN IMMEDIATE took effect,
    # the read and the write are separate and this succeeds.
    async with mk() as s:
        await s.execute(select(ResearchRun).limit(1))
        await s.execute(ResearchRun.__table__.insert().values(
            id="x" * 32, objective="read then write", status=RunStatus.QUEUED,
            scope_json={}))
        await s.commit()
        print("   read-then-write: OK")

    # Confirm the driver's own view of the opener.
    async with engine.connect() as c:
        conn = c.sync_connection
        t = conn.begin()
        raw = conn.connection
        print(f"   inside explicit txn: sqlite3.in_transaction={raw.in_transaction}")
        t.commit()


asyncio.run(main())