"""Tests for Resumable Checkpoints and Durable State Storage."""

import hashlib
import json

import pytest

from intelx.core.checkpoint import Checkpoint, CheckpointManager
from intelx.core.persistence import DurableResearchStore


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


def test_durable_research_store_optimistic_concurrency(tmp_path):
    """Verify SQLite WAL state persistence, optimistic concurrency conflicts, and outbox."""
    db_file = str(tmp_path / "test_durable.db")
    with DurableResearchStore(db_file) as store:
        # Save initial version 1 (expected 0)
        v1 = store.save_state(
            tenant="tenant-1",
            research_id="run-99",
            state_json=json.dumps({"phase": "INIT"}),
            state_hash="hash-1",
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
                state_hash="hash-race",
                expected_version=0,
            )

        # Successful update to version 2 (expected 1)
        v2 = store.save_state(
            tenant="tenant-1",
            research_id="run-99",
            state_json=json.dumps({"phase": "DISCOVERING"}),
            state_hash="hash-2",
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
