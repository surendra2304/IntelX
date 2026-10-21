"""INTELX Resumable Checkpoint Management and State Recovery."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Snapshot of research pipeline state at a discrete phase boundary."""

    research_id: str
    phase: str
    version: int
    state_hash: str
    payload: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)

    def is_valid_hash(self) -> bool:
        """Verify that payload matches state_hash."""
        if self.payload is None:
            return True
        computed = hashlib.sha256(
            json.dumps(self.payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return computed == self.state_hash


class CheckpointManager:
    """Manages creation, retrieval, and validation of durable research checkpoints."""

    def __init__(self) -> None:
        self.history: dict[str, list[Checkpoint]] = {}
        self.latest: dict[str, Checkpoint] = {}

    def save(self, checkpoint: Checkpoint) -> None:
        """Save checkpoint for research run, appending to version history."""
        self.latest[checkpoint.research_id] = checkpoint
        if checkpoint.research_id not in self.history:
            self.history[checkpoint.research_id] = []
        self.history[checkpoint.research_id].append(checkpoint)

    def load(self, research_id: str) -> Checkpoint | None:
        """Retrieve most recent checkpoint for research run."""
        return self.latest.get(research_id)

    def load_version(self, research_id: str, version: int) -> Checkpoint | None:
        """Retrieve a specific versioned checkpoint for research run."""
        for cp in self.history.get(research_id, []):
            if cp.version == version:
                return cp
        return None

    def rollback_to(self, research_id: str, phase: str) -> Checkpoint | None:
        """Rollback research run to the most recent checkpoint of a prior phase."""
        checkpoints = self.history.get(research_id, [])
        for cp in reversed(checkpoints):
            if cp.phase == phase:
                self.latest[research_id] = cp
                return cp
        return None

    def list_history(self, research_id: str) -> list[Checkpoint]:
        """Return all historical checkpoints for a given research run."""
        return list(self.history.get(research_id, []))

    def invalidate(self, research_id: str) -> None:
        """Clear cached and historical checkpoints for a research run."""
        self.latest.pop(research_id, None)
        self.history.pop(research_id, None)


__all__ = [
    "Checkpoint",
    "CheckpointManager",
]
