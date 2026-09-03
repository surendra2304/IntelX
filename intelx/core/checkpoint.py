"""INTELX Resumable Checkpoint Management and State Recovery."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Snapshot of research pipeline state at a discrete phase boundary."""

    research_id: str
    phase: str
    version: int
    state_hash: str
    payload: dict[str, Any] | None = None
    created_at: float = time.time()


class CheckpointManager:
    """Manages creation, retrieval, and validation of durable research checkpoints."""

    def __init__(self) -> None:
        self.latest: dict[str, Checkpoint] = {}

    def save(self, checkpoint: Checkpoint) -> None:
        """Save latest checkpoint for research run."""
        self.latest[checkpoint.research_id] = checkpoint

    def load(self, research_id: str) -> Checkpoint | None:
        """Retrieve most recent checkpoint for research run."""
        return self.latest.get(research_id)

    def invalidate(self, research_id: str) -> None:
        """Clear cached checkpoint."""
        self.latest.pop(research_id, None)
