"""INTELX Durable State Machine Storage and Transactional Outbox."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class StateIntegrityError(RuntimeError):
    """Raised when persisted research JSON or its SHA-256 digest is invalid."""


def _validated_state(state_json: str) -> tuple[dict[str, Any], str]:
    """Parse a JSON object and compute its deterministic integrity digest."""
    if not isinstance(state_json, str):
        raise ValueError("state_json must be a JSON string")
    try:
        state = json.loads(state_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("state_json must contain valid JSON") from exc
    if not isinstance(state, dict):
        raise ValueError("state_json must encode a JSON object")
    try:
        canonical = json.dumps(
            state,
            sort_keys=True,
            default=str,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("state_json must contain valid JSON-compatible values") from exc
    return state, hashlib.sha256(canonical).hexdigest()


def _require_identifier(value: str, name: str) -> str:
    """Validate tenant and research identifiers before database operations."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


class DurableResearchStore:
    """Thread-safe SQLite WAL-backed storage for versioned research states and transactional outbox."""

    def __init__(self, db_path: str = "./data/intelx_durable.db") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
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
        """Atomically persist validated state with integrity and concurrency checks."""
        tenant = _require_identifier(tenant, "tenant")
        research_id = _require_identifier(research_id, "research_id")
        _state, computed_hash = _validated_state(state_json)
        if not isinstance(state_hash, str) or not hmac.compare_digest(computed_hash, state_hash):
            raise ValueError("state_hash does not match the canonical state_json")
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 0
        ):
            raise ValueError("expected_version must be a non-negative integer")

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
                (tenant, research_id, new_version, state_json, computed_hash, time.time()),
            )
            return new_version

    def load_state(self, tenant: str, research_id: str) -> dict[str, Any] | None:
        """Load state only when its stored JSON and integrity digest still agree."""
        tenant = _require_identifier(tenant, "tenant")
        research_id = _require_identifier(research_id, "research_id")
        with self.lock, self.conn:
            row = self.conn.execute(
                "SELECT state_json, version, state_hash FROM research_state WHERE tenant_id=? AND research_id=?",
                (tenant, research_id),
            ).fetchone()
            if row is None:
                return None
            try:
                state, computed_hash = _validated_state(row[0])
            except ValueError as exc:
                raise StateIntegrityError(
                    f"persisted state JSON is invalid for research '{research_id}'"
                ) from exc
            if not hmac.compare_digest(computed_hash, row[2]):
                raise StateIntegrityError(
                    f"persisted state hash mismatch for research '{research_id}'"
                )
            return {"state": state, "version": row[1], "state_hash": row[2]}

    def delete_state(self, tenant: str, research_id: str) -> bool:
        """Delete persisted state for a research run."""
        with self.lock, self.conn:
            cur = self.conn.execute(
                "DELETE FROM research_state WHERE tenant_id=? AND research_id=?",
                (tenant, research_id),
            )
            return cur.rowcount > 0

    def append_outbox(
        self,
        tenant: str,
        research_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        """Append a JSON-safe event to the transactional outbox."""
        tenant = _require_identifier(tenant, "tenant")
        research_id = _require_identifier(research_id, "research_id")
        event_type = _require_identifier(event_type, "event_type")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        payload_json = json.dumps(payload, sort_keys=True, allow_nan=False)
        with self.lock, self.conn:
            cursor = self.conn.execute(
                "INSERT INTO outbox (tenant_id, research_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    tenant,
                    research_id,
                    event_type,
                    payload_json,
                    time.time(),
                ),
            )
            return cursor.lastrowid or 0

    def fetch_undelivered_outbox(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch a bounded page of pending outbox events for worker dispatch."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise ValueError("limit must be an integer between 1 and 1000")
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

    def close(self) -> None:
        """Close database connection."""
        with self.lock:
            self.conn.close()

    def __enter__(self) -> DurableResearchStore:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


__all__ = ["DurableResearchStore", "StateIntegrityError"]
