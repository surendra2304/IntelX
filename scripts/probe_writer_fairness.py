"""The last mechanism available inside SQLite: a dedicated writer connection.

If the cause were read-after-write on one connection, moving reads to their own
connection would fix it. If the cause is simply that five workers each open a
deferred transaction that must be upgraded while four others are mid-upgrade,
then serialising *writers* removes the upgrade race without touching reads.

This measures the shape of the contention directly rather than inferring it:
holds a real write lock on one connection and measures how long a second writer
waits, with and without a BEGIN IMMEDIATE taken up front. BEGIN IMMEDIATE is
issued as plain SQL on a connection whose isolation_level is None, which pysqlite
cannot swallow -- the arm the earlier do_begin override could not actually run.
"""

import asyncio
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(".").resolve()))

DB = Path("./data/probe_fair.db").resolve()
for suf in ("", "-wal", "-shm"):
    f = Path(str(DB) + suf)
    if f.exists():
        try:
            f.unlink()
        except OSError:
            pass

ARM = sys.argv[1] if len(sys.argv) > 1 else "deferred"


def connect(immediate: bool):
    c = sqlite3.connect(DB.as_posix(), timeout=5.0, isolation_level=None,
                        check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def setup():
    c = sqlite3.connect(DB.as_posix(), isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS t(id TEXT PRIMARY KEY, v TEXT)")
    c.commit()
    c.close()


def write_txn(c, oid, value, hold_s, read_first=False):
    """One write transaction, optionally holding it open for hold_s seconds.

    read_first reproduces the pipeline shape that fails: a transaction takes a
    read snapshot, then tries to upgrade it into a write.
    """
    if ARM == "immediate":
        c.execute("BEGIN IMMEDIATE")
    else:
        c.execute("BEGIN")
    if read_first:
        # Take a snapshot first, then do slow work, then upgrade to a write.
        c.execute("SELECT count(*) FROM t").fetchone()
        if hold_s:
            time.sleep(hold_s)
    c.execute("INSERT OR REPLACE INTO t VALUES (?,?)", (oid, value))
    if hold_s and not read_first:
        time.sleep(hold_s)
    c.execute("COMMIT")


async def main():
    setup()
    n_workers = 5
    print(f"ARM={ARM}  workers={n_workers}  "
          f"last txn READS FIRST (snapshot upgrade), 5 workers")

    for trial in range(1, 4):
        c = sqlite3.connect(DB.as_posix(), isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("DELETE FROM t")
        c.commit()
        c.close()

        results = {}

        def worker(i):
            c = connect(ARM == "immediate")
            t0 = time.perf_counter()
            try:
                write_txn(c, f"a{i}", "1", 0.0)
                for j in range(2):
                    write_txn(c, f"a{i}-{j}", "x", 0.05)
                write_txn(c, f"z{i}", "last", 0.30, read_first=True)
                results[i] = ("ok", time.perf_counter() - t0)
            except Exception as e:
                results[i] = (type(e).__name__, time.perf_counter() - t0)
            finally:
                c.close()

        t0 = time.perf_counter()
        await asyncio.gather(*[asyncio.to_thread(worker, i) for i in range(n_workers)])
        wall = time.perf_counter() - t0
        bad = {i: r for i, r in results.items() if r[0] != "ok"}
        print(f"  trial {trial}: wall {wall:6.2f}s  ok={n_workers - len(bad)}/{n_workers}"
              f"  worst={max(r[1] for r in results.values()):6.2f}s"
              + (f"  FAILURES={bad}" if bad else ""))


asyncio.run(main())