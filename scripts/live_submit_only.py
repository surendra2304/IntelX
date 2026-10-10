"""Live submission probe that stays inside the 50 req/hour Friday budget.

The previous version polled /api/v1/friday/research/{run_id} once a second, and
every one of those GETs goes through the same Friday auth dependency and the same
50/hour limiter -- so the probe exhausted its own budget and then measured 429
instead of the fix. Terminal state is read from the live SQLite database here,
which costs no quota at all.

Budget used by this script: one POST per submission and nothing else.
"""

import concurrent.futures as cf
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import httpx

DB = "D:/app/data/intelx.db"
env = {}
for ln in Path("D:/FRIDAY Universe/IntelX/.env").read_text(
    encoding="utf-8", errors="replace"
).splitlines():
    ln = ln.strip()
    if ln and not ln.startswith("#") and "=" in ln:
        k, v = ln.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
key = env.get("INTELX_API_KEY") or env.get("FRIDAY_API_KEY") or env.get("API_KEY")
H = {"X-API-Key": key, "Authorization": f"Bearer {key}"}
SUBMIT = "http://127.0.0.1:8105/api/v1/friday/research"

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
WAIT = float(sys.argv[2]) if len(sys.argv) > 2 else 240.0


def submit(tag):
    body = {
        "friday_request_id": f"fr-{uuid.uuid4().hex[:10]}",
        "objective": f"live verify {tag}",
        "query_scope": {"query": f"live verify {tag}"},
        "max_findings": 2,
    }
    t0 = time.perf_counter()
    try:
        r = httpx.post(SUBMIT, headers=H, json=body, timeout=120.0)
        el = time.perf_counter() - t0
        rid = None
        try:
            rid = (r.json() or {}).get("intelx_run_id")
        except Exception:
            pass
        return {"tag": tag, "code": r.status_code, "s": el, "run_id": rid,
                "body": r.text[:120]}
    except Exception as e:
        return {"tag": tag, "code": type(e).__name__,
                "s": time.perf_counter() - t0, "run_id": None, "body": str(e)[:120]}


def db_state(ids):
    """Terminal state straight from the live DB. No HTTP, no quota."""
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    rows = con.execute(
        f"SELECT id, status, outcome, "
        f"ROUND((julianday('now')-julianday(started_at))*86400,1) "
        f"FROM research_runs WHERE id IN ({q})", ids).fetchall()
    con.close()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


print(f"budget: {N} POSTs against a 50/hour Friday limit\n")
t0 = time.perf_counter()
with cf.ThreadPoolExecutor(max_workers=N) as ex:
    res = list(ex.map(lambda i: submit(f"c{i}"), range(N)))
wall = time.perf_counter() - t0

print(f"submission wall {wall:.3f}s")
for x in res:
    print(f"  {x['tag']:<4} HTTP {x['code']}  {x['s']:.3f}s  "
          f"run={x['run_id']}  {x['body'][:60]}")

codes = [x["code"] for x in res]
print(f"\naccepted {codes.count(201)}/{N}   "
      f"slowest {max(x['s'] for x in res):.3f}s   "
      f"status codes {sorted(set(str(c) for c in codes))}")

ids = [x["run_id"] for x in res if x["run_id"]]
if not ids:
    print("\nno run ids to verify")
    sys.exit(1)

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "REVIEW_REQUIRED"}
print(f"\npolling live DB for {len(ids)} runs (no HTTP quota used)...")
t0 = time.perf_counter()
while time.perf_counter() - t0 < WAIT:
    st = db_state(ids)
    done = [i for i in ids if st.get(i, ("QUEUED",))[0] in TERMINAL]
    print(f"  t+{time.perf_counter() - t0:6.1f}s  terminal {len(done)}/{len(ids)}  "
          + " ".join(f"{v[0][:4]}" for v in st.values()))
    if len(done) == len(ids):
        break
    time.sleep(10)

st = db_state(ids)
print("\nterminal state from the live DB:")
ok = 0
for rid in ids:
    s, o, age = st.get(rid, ("NOT_FOUND", None, None))
    good = s in ("COMPLETED", "REVIEW_REQUIRED")
    ok += 1 if good else 0
    print(f"  {rid[:12]}  {s:<15} {str(o):<22} age={age}s  {'OK' if good else 'BAD'}")
print(f"\n==== {ok}/{len(ids)} accepted AND finished non-FAILED ====")
sys.exit(0 if ok == len(ids) and codes.count(201) == N else 1)