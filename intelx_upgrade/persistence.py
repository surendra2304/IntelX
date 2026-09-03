from __future__ import annotations
from pathlib import Path
import sqlite3, threading, time, json

class DurableResearchStore:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn=sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.lock=threading.RLock()
        with self.lock, self.conn:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS research_state(
              tenant_id TEXT NOT NULL, research_id TEXT NOT NULL, version INTEGER NOT NULL,
              state_json TEXT NOT NULL, state_hash TEXT NOT NULL, updated_at REAL NOT NULL,
              PRIMARY KEY(tenant_id,research_id));
            CREATE TABLE IF NOT EXISTS outbox(
              id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL,
              research_id TEXT NOT NULL, event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL, created_at REAL NOT NULL, delivered_at REAL);
            """)

    def save_state(self, tenant, research_id, state_json, state_hash, expected_version):
        with self.lock, self.conn:
            row=self.conn.execute(
                "SELECT version FROM research_state WHERE tenant_id=? AND research_id=?",
                (tenant,research_id)).fetchone()
            current=0 if row is None else row[0]
            if current != expected_version:
                raise RuntimeError("optimistic concurrency conflict")
            self.conn.execute(
                "INSERT INTO research_state VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(tenant_id,research_id) DO UPDATE SET version=excluded.version,"
                "state_json=excluded.state_json,state_hash=excluded.state_hash,updated_at=excluded.updated_at",
                (tenant,research_id,current+1,state_json,state_hash,time.time()))
            return current+1

    def append_outbox(self, tenant, research_id, event_type, payload):
        with self.lock, self.conn:
            self.conn.execute("INSERT INTO outbox(tenant_id,research_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                              (tenant,research_id,event_type,json.dumps(payload,sort_keys=True),time.time()))
