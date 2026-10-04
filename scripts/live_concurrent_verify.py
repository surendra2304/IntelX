"""Drive 5 concurrent live HTTP submissions and verify each run reaches a
non-FAILED terminal state.

A 201 only means the submission was accepted; the run is executed afterwards.
This polls each run to its terminal state and reports status, outcome and
latency, so a submission that is accepted and then dies is not counted as a pass.
"""

import concurrent.futures as cf
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

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
BASE = "http://127.0.0.1:8105"
SUBMIT = f"{BASE}/api/v1/friday/research"

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 2
WAIT = float(sys.argv[3]) if len(sys.argv) > 3 else 90.0


def submit(tag):
    body = {
        "friday_request_id": f"fr-{uuid.uuid4().hex[:10]}",
        "objective": f"Verify concurrent write deadline {tag}",
        "query_scope": {"query": f"concurrent write deadline {tag}"},
        "max_findings": 2,
    }
    t0 = time.monotonic()
    try:
        r = httpx.post(SUBMIT, headers=H, json=body, timeout=120.0)
        el = time.monotonic() - t0
        rid = None
        try:
            rid = (r.json() or {}).get("intelx_run_id") or (r.json() or {}).get("run_id")
        except Exception:
            pass
        return {"tag": tag, "submit_s": el, "code": r.status_code, "run_id": rid}
    except Exception as e:
        return {"tag": tag, "submit_s": time.monotonic() - t0,
                "code": type(e).__name__, "run_id": None}


def poll(rid, budget):
    """Poll a run to a terminal state; returns (status, outcome, seconds)."""
    t0 = time.monotonic()
    terminal = {"COMPLETED", "FAILED", "CANCELLED", "REVIEW_REQUIRED"}
    last = None
    while time.monotonic() - t0 < budget:
        try:
            r = httpx.get(f"{BASE}/api/v1/friday/research/{rid}", headers=H, timeout=30.0)
            if r.status_code != 200:
                time.sleep(1.0)
                continue
            d = r.json()
            s = d.get("status") or (d.get("run") or {}).get("status")
            o = d.get("outcome") or (d.get("run") or {}).get("outcome")
            last = (s, o)
            if s in terminal:
                return s, o, time.monotonic() - t0
        except Exception:
            pass
        time.sleep(1.0)
    return (last or ("TIMEOUT", None)) + (time.monotonic() - t0,)


total = ok = 0
print(f"driving {N} concurrent submissions x {ROUNDS} round(s), full fleet up")
for rnd in range(1, ROUNDS + 1):
    t0 = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=N) as ex:
        res = list(ex.map(lambda i: submit(f"r{rnd}c{i}"), range(N)))
    wall = time.monotonic() - t0
    accepted = sum(1 for x in res if x["code"] == 201)
    print(f"\n-- round {rnd}: submission wall {wall:.2f}s, accepted {accepted}/{N} --")
    for x in res:
        total += 1
        if x["code"] == 201 and x["run_id"]:
            s, o, secs = poll(x["run_id"], WAIT)
            good = s in ("COMPLETED", "REVIEW_REQUIRED")
            ok += 1 if good else 0
            print(f"  {x['tag']:<7} POST {x['code']} {x['submit_s']:5.2f}s -> "
                  f"{s:<15} {str(o):<22} {secs:6.2f}s  {'OK' if good else 'BAD'}")
        else:
            print(f"  {x['tag']:<7} POST {x['code']} {x['submit_s']:5.2f}s -> NO RUN  BAD")

print(f"\n==== {ok}/{total} submissions accepted AND finished in a non-FAILED state ====")
sys.exit(0 if ok == total else 1)