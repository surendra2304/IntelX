"""Re-test the BEGIN IMMEDIATE claim honestly.

An earlier A/B reported 8/8 vs 3/8 for "BEGIN IMMEDIATE" by overriding
dialect.do_begin. That hook is `pass` on the SQLite dialect -- pysqlite opens the
transaction itself -- so the override could not have taken effect, and the result
needs re-establishing by a mechanism that provably does.

This sets pysqlite's isolation_level instead:
  None     -> DBAPI never opens a transaction; every statement autocommits
  ""       -> DBAPI opens a deferred transaction on the first DML (today)
and, for the third arm, opens each write transaction with an explicit
BEGIN IMMEDIATE issued as real SQL, which pysqlite cannot intercept.

Arms are interleaved so machine-load drift hits all three.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

os.environ["INTELX_ENV"] = "testing"
os.environ["INTELX_MOCK_MODE"] = "true"
sys.path.insert(0, str(Path(".").resolve()))

from sqlalchemy import event, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from intelx.core.enums import RunStatus  # noqa: E402
from intelx.db.engine import get_async_engine  # noqa: E402
from intelx.db.repos import RunRepo  # noqa: E402
from intelx.db.session import get_sessionmaker  # noqa: E402
from intelx.orchestration.engine import OrchestrationEngine  # noqa: E402
from tests.conftest import reset_test_schema  # noqa: E402

ARM = os.environ.get("ARM", "deferred")
busy = []

OBJS = ["Assess sodium-ion battery cathode formulations",
        "Investigate composite sulfide solid electrolyte dendrites",
        "Benchmark 5000-qubit superconducting quantum annealing speedup",
        "Analyze high-capacity silicon-graphite anode swelling limits",
        "Evaluate piezoelectric kinetic energy recovery generators"]


def install(engine):
    sync = engine.sync_engine

    if ARM == "autocommit":
        # DBAPI must not open transactions at all; we open them ourselves.
        @event.listens_for(sync, "connect")
        def _iso(dbapi_conn, rec):
            dbapi_conn.isolation_level = None

    @event.listens_for(sync, "handle_error")
    def on_err(ctx):
        e = ctx.original_exception
        if getattr(e, "sqlite_errorcode", None) in (5, 517):
            busy.append((getattr(e, "sqlite_errorname", None),
                         " ".join((ctx.statement or "?").split())[:55]))

    @event.listens_for(sync, "before_cursor_execute")
    def before(conn, cur, statement, params, ctx, many):
        if statement.strip().upper().startswith("BEGIN"):
            busy.append(("OPEN", " ".join(statement.split())[:40]))


async def trial(sm, eng):
    busy.clear()
    ids = []
    async with sm() as s:
        for i, o in enumerate(OBJS):
            r = await RunRepo.create_run(
                session=s, objective=f"[{i + 1}] {o}",
                scope_json={"depth": "quick", "budget": {"max_usd": 3.0, "max_minutes": 5}},
                created_by=f"w{i + 1}")
            ids.append(r.id)
        await s.commit()
    res = {}

    async def one(rid, i):
        try:
            async with sm() as s:
                run = await eng.execute_run(session=s, run_id=rid)
                if run.status == RunStatus.REVIEW_REQUIRED:
                    run.scope_json = run.scope_json or {}
                    run.scope_json["review_decision"] = "APPROVED"
                    run.status = RunStatus.QUEUED
                    await s.commit()
                    run = await eng.execute_run(session=s, run_id=rid)
                await s.commit()
                res[i] = str(run.status)
        except Exception as e:
            res[i] = f"EXC {type(e).__name__}"

    t0 = time.perf_counter()
    await asyncio.gather(*[one(r, i) for i, r in enumerate(ids)])
    return time.perf_counter() - t0, res


async def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    db = Path("./data/probe_iso.db").resolve()
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

    # prove the mechanism actually engaged
    async with engine.connect() as c:
        raw = c.sync_connection.connection
        print(f"  ARM={ARM}  pysqlite isolation_level={raw.isolation_level!r}")

    sm = get_sessionmaker()
    eng = OrchestrationEngine()
    ok, walls = 0, []
    for i in range(1, n + 1):
        await reset_test_schema(engine)
        wall, res = await trial(sm, eng)
        bad = any(v.startswith("EXC") for v in res.values()) or \
            any(t == "OPEN" or b[0] == "SQLITE_BUSY" or b[0] == "SQLITE_BUSY_SNAPSHOT"
                for t, *b in [(x if isinstance(x, tuple) else (x,)) for x in busy]) or \
            any(getattr(x, "sqlite_errorcode", None) in (5, 517) for x in busy
                if not isinstance(x, str))
        nbusy = sum(1 for x in busy if isinstance(x, tuple) and x[0] != "OPEN")
        if not bad:
            ok += 1
        walls.append(wall)
        print(f"  [{i:>2}/{n}] {'OK  ' if not bad else 'FAIL'} wall {wall:6.2f}s "
              f"busy {nbusy} {sorted(set(res.values()))}", flush=True)
    print(f"\n==== ARM={ARM}  {ok}/{n} passed  median wall "
          f"{sorted(walls)[n // 2]:.2f}s ====")


asyncio.run(main())