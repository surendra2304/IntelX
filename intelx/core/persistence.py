"""INTELX Durable State Machine Storage and Transactional Outbox."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class DurableResearchStore:
    """Thread-safe SQLite WAL-backed storage for versioned research states and transactional outbox."""

    def __init__(self, db_path: str = "./data/intelx_durable.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.lock = threading.RLock()
        with self.lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_state (
                    tenant_id TEXT NOT NULL,
                    research_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (tenant_id, research_id)
                );

                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    research_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    delivered_at REAL
                );
                """
            )

    def save_state(
        self,
        tenant: str,
        research_id: str,
        state_json: str,
        state_hash: str,
        expected_version: int,
    ) -> int:
        """Atomically persist state with optimistic concurrency check."""
        with self.lock, self.conn:
            row = self.conn.execute(
                "SELECT version FROM research_state WHERE tenant_id=? AND research_id=?",
                (tenant, research_id),
            ).fetchone()
            current = 0 if row is None else row[0]
            if current != expected_version:
                raise RuntimeError(
                    f"optimistic concurrency conflict: current version {current} != expected {expected_version}"
                )
            new_version = current + 1
            self.conn.execute(
                """
                INSERT INTO research_state VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, research_id) DO UPDATE SET
                    version = excluded.version,
                    state_json = excluded.state_json,
                    state_hash = excluded.state_hash,
                    updated_at = excluded.updated_at
                """,
                (tenant, research_id, new_version, state_json, state_hash, time.time()),
            )
            return new_version

    def load_state(self, tenant: str, research_id: str) -> dict[str, Any] | None:
        """Load persisted state for research run."""
        with self.lock, self.conn:
            row = self.conn.execute(
                "SELECT state_json, version, state_hash FROM research_state WHERE tenant_id=? AND research_id=?",
                (tenant, research_id),
            ).fetchone()
            if not row:
                return None
            return {
                "state": json.loads(row[0]),
                "version": row[1],
                "state_hash": row[2],
            }

    def append_outbox(
        self,
        tenant: str,
        research_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        """Append event to transactional outbox."""
        with self.lock, self.conn:
            cursor = self.conn.execute(
                "INSERT INTO outbox (tenant_id, research_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (tenant, research_id, event_type, json.dumps(payload, sort_keys=True, default=str), time.time()),
            )
            return cursor.lastrowid or 0

    def fetch_undelivered_outbox(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch pending outbox events for background worker dispatch."""
        with self.lock, self.conn:
            rows = self.conn.execute(
                "SELECT id, tenant_id, research_id, event_type, payload_json, created_at FROM outbox WHERE delivered_at IS NULL ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "tenant_id": r[1],
                    "research_id": r[2],
                    "event_type": r[3],
                    "payload": json.loads(r[4]),
                    "created_at": r[5],
                }
                for r in rows
            ]

    def mark_outbox_delivered(self, event_id: int) -> None:
        """Mark outbox event as delivered."""
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE outbox SET delivered_at=? WHERE id=?",
                (time.time(), event_id),
            )
