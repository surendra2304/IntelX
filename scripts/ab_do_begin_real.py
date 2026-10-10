"""A/B the real pipeline with a do_begin BEGIN IMMEDIATE override that provably
fires, against today's deferred behaviour.

Mechanism, established separately:
  - raw sqlite3, 5 workers, read-then-write transaction:
      deferred BEGIN  -> 1/5 succeed, 4x OperationalError
      BEGIN IMMEDIATE -> 5/5 succeed, 3/3 trials
  - the SQLite dialect's do_begin is `pass`, and Connection._begin_impl calls it
    for every transaction, so overriding it emits a real BEGIN IMMEDIATE.

Arms interleaved by the caller.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

os.environ["INTELX_ENV"] = "testing"
os.environ["INTELX_MOCK_MODE"] = "true"
sys.path.insert(0, str(Path(".").resolve()))

from sqlalchemy import event  # noqa: E402

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


def do_begin_immediate(dbapi_connection):
    dbapi_connection.execute("BEGIN IMMEDIATE")


def install(engine):
    sync = engine.sync_engine
    if ARM == "immediate":
        sync.dialect.do_begin = do_begin_immediate

    @event.listens_for(sync, "handle_error")
    def on_err(ctx):
        e = ctx.original_exception
        if getattr(e, "sqlite_errorcode", None) in (5, 517):
            busy.append((getattr(e, "sqlite_errorname", None),
                         " ".join((ctx.statement or "?").split())[:50]))


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
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    db = Path("./data/ab_dobegin.db").resolve()
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
    sm = get_sessionmaker()
    eng = OrchestrationEngine()
    print(f"  ARM={ARM}  do_begin={engine.sync_engine.dialect.do_begin.__name__}")

    ok, walls = 0, []
    for i in range(1, n + 1):
        await reset_test_schema(engine)
        wall, res = await trial(sm, eng)
        bad = any(v.startswith("EXC") for v in res.values()) or busy
        ok += 0 if bad else 1
        walls.append(wall)
        print(f"  [{i:>2}/{n}] {'OK  ' if not bad else 'FAIL'} wall {wall:6.2f}s "
              f"busy {len(busy)} {sorted(set(res.values()))}", flush=True)
    print(f"\n==== ARM={ARM}  {ok}/{n} passed  median wall {sorted(walls)[n // 2]:.2f}s ====")


asyncio.run(main())