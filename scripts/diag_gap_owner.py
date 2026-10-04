"""Name the stage that owns each intra-transaction gap.

Same interval instrumentation as diag_who_holds, plus a stage tag written by
wrapping the agents' execute() methods, so a 5-second gap between two writes is
attributed to the slow call that actually filled it.
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

from intelx.agents import analyst as analyst_mod  # noqa: E402
from intelx.agents import critic as critic_mod  # noqa: E402
from intelx.agents import extractor as extractor_mod  # noqa: E402
from intelx.agents import planner as planner_mod  # noqa: E402
from intelx.agents import retriever as retriever_mod  # noqa: E402
from intelx.agents import scout as scout_mod  # noqa: E402
from intelx.agents import synthesizer as synth_mod  # noqa: E402
from intelx.agents import verifier as verifier_mod  # noqa: E402
from intelx.core.enums import RunStatus  # noqa: E402
from intelx.db.engine import get_async_engine  # noqa: E402
from intelx.db.repos import RunRepo  # noqa: E402
from intelx.db.session import get_sessionmaker  # noqa: E402
from intelx.integrations import ecosystem_dispatch  # noqa: E402
from intelx.orchestration import events as events_mod  # noqa: E402
from intelx.orchestration.engine import OrchestrationEngine  # noqa: E402
from tests.conftest import reset_test_schema  # noqa: E402

WRITE_SQL = ("INSERT", "UPDATE", "DELETE", "REPLACE")
T0 = time.perf_counter()
stage = {"now": "init"}
intervals = {}
open_txn = {}
busy = []
gaps = []          # (duration, stage, from_stmt, to_stmt)


def wrap(mod, cls_name, label):
    cls = getattr(mod, cls_name, None)
    if cls is None:
        return
    orig = cls.execute

    async def patched(self, *a, **kw):
        stage["now"] = label
        try:
            return await orig(self, *a, **kw)
        finally:
            stage["now"] = "after:" + label
    cls.execute = patched


for m, c, l in ((planner_mod, "PlannerAgent", "planner"),
                (scout_mod, "ScoutAgent", "scout"),
                (retriever_mod, "RetrieverAgent", "retriever"),
                (extractor_mod, "ExtractorAgent", "extractor"),
                (verifier_mod, "VerifierAgent", "verifier"),
                (analyst_mod, "AnalystAgent", "analyst"),
                (critic_mod, "CriticAgent", "critic"),
                (synth_mod, "SynthesizerAgent", "synthesizer")):
    wrap(m, c, l)

_orig_dispatch = ecosystem_dispatch.dispatch_sequentially


async def dispatch_patched(**kw):
    stage["now"] = "external_dispatch"
    try:
        return await _orig_dispatch(**kw)
    finally:
        stage["now"] = "after:external_dispatch"


ecosystem_dispatch.dispatch_sequentially = dispatch_patched

_orig_emit = events_mod.emit_event


async def emit_patched(*a, **kw):
    stage["now"] = "emit_event"
    try:
        return await _orig_emit(*a, **kw)
    finally:
        stage["now"] = "after:emit_event"


events_mod.emit_event = emit_patched


def install(engine):
    sync = engine.sync_engine

    @event.listens_for(sync, "before_cursor_execute")
    def before(conn, cur, statement, parameters, context, executemany):
        now = time.perf_counter() - T0
        k = id(conn)
        head = statement.lstrip()
        is_w = head[:6].upper().startswith(WRITE_SQL)
        rec = open_txn.get(k)
        if rec is None:
            rec = {"t0": now, "w0": None, "w1": None, "n": 0, "tag": None,
                   "last_w_stage": None, "tl": []}
            open_txn[k] = rec
            rec["_keep"] = conn
        rec["n"] += 1
        tag = head.split()[0].upper()[:8] + " " + " ".join(head.split()[1:3])[:26]
        if rec["w0"] is not None and is_w:
            d = now - rec["w1"]
            if d > 0.5:
                gaps.append((d, rec["last_w_stage"], rec["tl"][-1], tag,
                             stage["now"]))
        if is_w:
            rec["w0"] = rec["w0"] or now
            rec["w1"] = now
            rec["tl"].append(tag)
            rec["last_w_stage"] = stage["now"]

    def close(conn, outcome):
        now = time.perf_counter() - T0
        k = id(conn)
        rec = open_txn.pop(k, None)
        if rec and rec["w0"] is not None:
            intervals[k] = {
                "w0": rec["w0"], "hold": now - rec["w0"],
                "span": now - rec["t0"], "n": rec["n"],
                "outcome": outcome, "tl": rec["tl"],
            }

    @event.listens_for(sync, "commit")
    def on_commit(conn):
        close(conn, "COMMIT")

    @event.listens_for(sync, "rollback")
    def on_rollback(conn):
        close(conn, "ROLLBACK")

    @event.listens_for(sync, "handle_error")
    def on_err(ctx):
        e = ctx.original_exception
        if getattr(e, "sqlite_errorcode", None) in (5, 517):
            busy.append(" ".join((ctx.statement or "?").split())[:70])


OBJS = ["Assess sodium-ion battery cathode formulations",
        "Investigate composite sulfide solid electrolyte dendrites",
        "Benchmark 5000-qubit superconducting quantum annealing speedup",
        "Analyze high-capacity silicon-graphite anode swelling limits",
        "Evaluate piezoelectric kinetic energy recovery generators"]


async def trial(sm, eng, n):
    intervals.clear()
    open_txn.clear()
    busy.clear()
    gaps.clear()
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

    await asyncio.gather(*[one(r, i) for i, r in enumerate(ids)])
    return busy, list(intervals.values()), res


async def main():
    db = Path("./data/gap_owner.db").resolve()
    url = f"sqlite+aiosqlite:///{db.as_posix()}"
    os.environ["INTELX_DB_URL"] = url
    engine = get_async_engine(url)
    install(engine)
    sm = get_sessionmaker()
    eng = OrchestrationEngine()

    agg = {}
    for n in range(1, 16):
        await reset_test_schema(engine)
        busy, ivs, res = await trial(sm, eng, n)
        for g in gaps:
            d, stg, a, b, endstg = g
            k = (stg or "?") + " -> " + (endstg or "?")
            cur = agg.setdefault(k, {"n": 0, "tot": 0.0, "max": 0.0})
            cur["n"] += 1
            cur["tot"] += d
            cur["max"] = max(cur["max"], d)
        print(f"  trial {n:>2}: busy {len(busy):>2} gaps>0.5s {len(gaps):>3} "
              f"txns {len(ivs):>3} {sorted(set(res.values()))}", flush=True)
        if busy:
            break

    print("\n  ===== INTRA-TRANSACTION GAPS > 0.5s, by stage that filled them =====")
    for stg, c in sorted(agg.items(), key=lambda kv: -kv[1]["tot"]):
        print(f"    {stg:<28} n={c['n']:<4} total {c['tot']:6.2f}s  max {c['max']:5.2f}s")


asyncio.run(main())