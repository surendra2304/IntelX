"""Loop the lock-guard tests N times and tally pass/fail. Determinism measurement only.

Corrected 2026-10-04. Two flaws made the number measure less than the report claimed:

1. It ran only `test_concurrency.py` and `test_concurrent_runs.py` -- 4 tests -- while the
   lock guards are 17 across three files. `test_release_writer_lock_lifecycle.py`, which
   covers the writer-lock boundary this whole line of work is about, was never executed.
2. It passed no `-m "not live"`, so any live-marked test in those files would run against
   real provider keys and make the tally depend on the environment rather than the code.

The test environment is also pinned explicitly here rather than left to whatever the
caller exported. `tests/conftest.py` does force the same values at import, so this is
belt-and-braces -- but the instrument should not depend on that remaining true.
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEST_DB = (REPO / "data" / "test_intelx.db").resolve()

LOCK_GUARD_TESTS = (
    "tests/test_concurrency.py",
    "tests/test_concurrent_runs.py",
    "tests/test_release_writer_lock_lifecycle.py",
)

CHILD_ENV = {
    **os.environ,
    "INTELX_ENV": "testing",
    "INTELX_MOCK_MODE": "true",
    "INTELX_DB_URL": f"sqlite+aiosqlite:///{TEST_DB.as_posix()}",
    # The lock guards are timing-sensitive; inheriting a caller's thread or debug
    # settings would change what is being measured.
    "PYTHONHASHSEED": "0",
}

N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
fails = []
for i in range(1, N + 1):
    t0 = time.time()
    p = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *LOCK_GUARD_TESTS,
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-m",
            "not live",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=CHILD_ENV,
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
        failed = re.findall(r"^FAILED (\S+)", p.stdout, re.M)
        fails.append(
            {
                "i": i,
                "failed": failed,
                "exceptions": sorted(set(excs)),
                "sql": sorted(set(sqls)),
                "first_errors": errs[:6],
            }
        )

print("\n==== SUMMARY ====")
print(f"{N - len(fails)}/{N} passed   ({len(LOCK_GUARD_TESTS)} lock-guard files per iteration)")
for f in fails:
    print(f"\n-- run {f['i']} --")
    if f["failed"]:
        print("  failed:", f["failed"])
    print("  exceptions:", f["exceptions"])
    print("  sql:", f["sql"])
    for e in f["first_errors"]:
        print("  E:", e[:300])
sys.exit(1 if fails else 0)
