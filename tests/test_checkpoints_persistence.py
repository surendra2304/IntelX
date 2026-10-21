"""Tests for Resumable Checkpoints and Durable State Storage."""

import hashlib
import json

import pytest

from intelx.core.checkpoint import Checkpoint, CheckpointManager
from intelx.core.persistence import DurableResearchStore, StateIntegrityError


def test_checkpoint_manager_lifecycle():
    """Verify save, load, history tracking, hash integrity, and rollback."""
    manager = CheckpointManager()
    payload_plan = {"plan_items": ["subq-1", "subq-2"]}
    hash_plan = hashlib.sha256(json.dumps(payload_plan, sort_keys=True).encode("utf-8")).hexdigest()

    cp1 = Checkpoint(
        research_id="run-500",
        phase="PLANNING",
        version=1,
        state_hash=hash_plan,
        payload=payload_plan,
    )
    assert cp1.is_valid_hash() is True

    manager.save(cp1)
    assert manager.load("run-500") == cp1

    # Second phase checkpoint
    payload_search = {"sources": ["src-1", "src-2"]}
    hash_search = hashlib.sha256(
        json.dumps(payload_search, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cp2 = Checkpoint(
        research_id="run-500",
        phase="SEARCHING",
        version=2,
        state_hash=hash_search,
        payload=payload_search,
    )
    manager.save(cp2)

    assert manager.load("run-500") == cp2
    assert len(manager.list_history("run-500")) == 2
    assert manager.load_version("run-500", 1) == cp1

    # Rollback to PLANNING
    rolled_back = manager.rollback_to("run-500", "PLANNING")
    assert rolled_back == cp1
    assert manager.load("run-500") == cp1

    # Invalidate
    manager.invalidate("run-500")
    assert manager.load("run-500") is None
    assert len(manager.list_history("run-500")) == 0


def test_checkpoint_manager_rejects_bad_hashes_and_non_monotonic_versions():
    manager = CheckpointManager()
    with pytest.raises(Exception, match="payload hash mismatch"):
        manager.save(Checkpoint("run-1", "PLANNING", 1, "wrong", {"x": 1}))

    payload = {"x": 1}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    manager.save(Checkpoint("run-1", "PLANNING", 1, digest, payload))
    with pytest.raises(ValueError, match="must exceed existing version"):
        manager.save(Checkpoint("run-1", "SEARCHING", 1, digest, payload))

    loaded = manager.load("run-1")
    assert loaded is not None
    loaded.payload["x"] = 999
    assert manager.load("run-1").payload == {"x": 1}


def test_checkpoint_manager_bounds_history_and_rejects_invalid_creation():
    manager = CheckpointManager(max_history_per_run=2)
    for version in (1, 2, 3):
        payload = {"version": version}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        manager.save(Checkpoint("run-2", f"PHASE-{version}", version, digest, payload))
    assert [item.version for item in manager.list_history("run-2")] == [2, 3]
    assert manager.load_version("run-2", 1) is None

    with pytest.raises(ValueError, match="positive integer"):
        CheckpointManager(max_history_per_run=0)
    with pytest.raises(ValueError, match="positive integer"):
        Checkpoint("run-2", "PHASE", True, "hash")


def test_durable_store_rejects_invalid_state_json_and_hash(tmp_path):
    with DurableResearchStore(str(tmp_path / "invalid.db")) as store:
        with pytest.raises(ValueError, match="valid JSON"):
            store.save_state("tenant", "research", "{not json}", "0" * 64, 0)
        with pytest.raises(ValueError, match="does not match"):
            store.save_state("tenant", "research", '{"phase":"INIT"}', "0" * 64, 0)
        with pytest.raises(ValueError, match="non-negative integer"):
            store.save_state("tenant", "research", "{}", hashlib.sha256(b"{}").hexdigest(), True)

        assert store.load_state("tenant", "research") is None


def test_durable_store_detects_state_tampering_and_bounds_outbox_fetch(tmp_path):
    db_file = str(tmp_path / "tampered.db")
    digest = hashlib.sha256(json.dumps({"phase": "SAFE"}, sort_keys=True).encode("utf-8")).hexdigest()
    with DurableResearchStore(db_file) as store:
        store.save_state("tenant", "research", '{"phase": "SAFE"}', digest, 0)
        store.conn.execute(
            "UPDATE research_state SET state_json=? WHERE tenant_id=? AND research_id=?",
            ('{"phase": "TAMPERED"}', "tenant", "research"),
        )
        with pytest.raises(StateIntegrityError, match="hash mismatch"):
            store.load_state("tenant", "research")
        with pytest.raises(ValueError, match="between 1 and 1000"):
            store.fetch_undelivered_outbox(limit=-1)


def test_durable_research_store_optimistic_concurrency(tmp_path):
    """Verify SQLite WAL state persistence, optimistic concurrency conflicts, and outbox."""
    db_file = str(tmp_path / "test_durable.db")
    with DurableResearchStore(db_file) as store:
        # Save initial version 1 (expected 0)
        v1 = store.save_state(
            tenant="tenant-1",
            research_id="run-99",
            state_json=json.dumps({"phase": "INIT"}),
            state_hash=hashlib.sha256(json.dumps({"phase": "INIT"}, sort_keys=True).encode("utf-8")).hexdigest(),
            expected_version=0,
        )
        assert v1 == 1

        # Load state
        loaded = store.load_state(tenant="tenant-1", research_id="run-99")
        assert loaded is not None
        assert loaded["version"] == 1
        assert loaded["state"]["phase"] == "INIT"

        # Concurrency conflict: expecting 0 when current is 1
        with pytest.raises(RuntimeError, match="optimistic concurrency conflict"):
            store.save_state(
                tenant="tenant-1",
                research_id="run-99",
                state_json=json.dumps({"phase": "RACE"}),
                state_hash=hashlib.sha256(json.dumps({"phase": "RACE"}, sort_keys=True).encode("utf-8")).hexdigest(),
                expected_version=0,
            )

        # Successful update to version 2 (expected 1)
        v2 = store.save_state(
            tenant="tenant-1",
            research_id="run-99",
            state_json=json.dumps({"phase": "DISCOVERING"}),
            state_hash=hashlib.sha256(json.dumps({"phase": "DISCOVERING"}, sort_keys=True).encode("utf-8")).hexdigest(),
            expected_version=1,
        )
        assert v2 == 2

        # Outbox event
        event_id = store.append_outbox(
            tenant="tenant-1",
            research_id="run-99",
            event_type="research.discovered",
            payload={"sources_count": 5},
        )
        assert event_id > 0

        # Fetch pending outbox
        pending = store.fetch_undelivered_outbox()
        assert len(pending) == 1
        assert pending[0]["id"] == event_id
        assert pending[0]["event_type"] == "research.discovered"

        # Mark delivered
        store.mark_outbox_delivered(event_id)
        assert len(store.fetch_undelivered_outbox()) == 0

        # Delete state
        assert store.delete_state(tenant="tenant-1", research_id="run-99") is True
        assert store.load_state(tenant="tenant-1", research_id="run-99") is None
