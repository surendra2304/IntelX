"""Loop the concurrency tests N times and tally pass/fail. Determinism measurement only."""

import re
import subprocess
import sys
import time

N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
fails = []
for i in range(1, N + 1):
    t0 = time.time()
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_concurrency.py",
         "tests/test_concurrent_runs.py", "-q", "--no-header", "-p", "no:cacheprovider"],
        capture_output=True, text=True,
    )
    dt = time.time() - t0
    tail = [ln for ln in p.stdout.strip().splitlines() if ln.strip()]
    verdict = tail[-1] if tail else "NO OUTPUT"
    ok = p.returncode == 0
    print(f"[{i:>2}/{N}] {'PASS' if ok else 'FAIL'}  {dt:6.1f}s  {verdict}", flush=True)
    if not ok:
        errs = re.findall(r"^E\s+(\S.*)$", p.stdout, re.M)
        sqls = re.findall(r"SQL: (\w+ [^,]+)", p.stdout)
        excs = re.findall(r"^E\s+(\w+(?:Error|Exception))", p.stdout, re.M)
        fails.append({
            "i": i,
            "exceptions": sorted(set(excs)),
            "sql": sorted(set(sqls)),
            "first_errors": errs[:6],
        })

print("\n==== SUMMARY ====")
print(f"{N - len(fails)}/{N} passed")
for f in fails:
    print(f"\n-- run {f['i']} --")
    print("  exceptions:", f["exceptions"])
    print("  sql:", f["sql"])
    for e in f["first_errors"]:
        print("  E:", e[:300])
sys.exit(1 if fails else 0)