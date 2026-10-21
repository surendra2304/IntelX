"""INTELX Resumable Checkpoint Management and State Recovery."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any


class CheckpointIntegrityError(RuntimeError):
    """Raised when a stored checkpoint no longer matches its integrity hash."""


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Snapshot of research pipeline state at a discrete phase boundary."""

    research_id: str
    phase: str
    version: int
    state_hash: str
    payload: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.research_id, str) or not self.research_id.strip():
            raise ValueError("research_id must be a non-empty string")
        if not isinstance(self.phase, str) or not self.phase.strip():
            raise ValueError("phase must be a non-empty string")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("version must be a positive integer")
        if not isinstance(self.state_hash, str) or not self.state_hash.strip():
            raise ValueError("state_hash must be a non-empty string")
        if self.payload is not None and not isinstance(self.payload, dict):
            raise ValueError("checkpoint payload must be a dictionary or None")
        if (
            isinstance(self.created_at, bool)
            or not isinstance(self.created_at, (int, float))
            or not math.isfinite(self.created_at)
            or self.created_at < 0
        ):
            raise ValueError("created_at must be a finite non-negative timestamp")

    def is_valid_hash(self) -> bool:
        """Verify the state payload hash using the canonical JSON representation."""
        if self.payload is None:
            return True
        try:
            serialized = json.dumps(
                self.payload,
                sort_keys=True,
                default=str,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError):
            return False
        computed = hashlib.sha256(serialized).hexdigest()
        return computed == self.state_hash


class CheckpointManager:
    """Manage validated versioned checkpoints with bounded, thread-safe history."""

    def __init__(self, max_history_per_run: int = 1_000) -> None:
        if (
            isinstance(max_history_per_run, bool)
            or not isinstance(max_history_per_run, int)
            or max_history_per_run < 1
        ):
            raise ValueError("max_history_per_run must be a positive integer")
        self.max_history_per_run = max_history_per_run
        self.history: dict[str, list[Checkpoint]] = {}
        self.latest: dict[str, Checkpoint] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _clone(checkpoint: Checkpoint) -> Checkpoint:
        """Copy mutable payloads at manager boundaries to prevent external mutation."""
        return Checkpoint(
            research_id=checkpoint.research_id,
            phase=checkpoint.phase,
            version=checkpoint.version,
            state_hash=checkpoint.state_hash,
            payload=copy.deepcopy(checkpoint.payload),
            created_at=checkpoint.created_at,
        )

    def save(self, checkpoint: Checkpoint) -> None:
        """Persist only valid checkpoints with monotonically increasing versions."""
        stored = self._clone(checkpoint)
        if not stored.is_valid_hash():
            raise CheckpointIntegrityError(
                f"checkpoint payload hash mismatch for research '{stored.research_id}'"
            )

        with self._lock:
            history = self.history.setdefault(stored.research_id, [])
            current_max = max((item.version for item in history), default=0)
            if stored.version <= current_max:
                raise ValueError(
                    f"checkpoint version must exceed existing version {current_max}"
                )
            history.append(stored)
            if len(history) > self.max_history_per_run:
                del history[: len(history) - self.max_history_per_run]
            self.latest[stored.research_id] = stored

    def load(self, research_id: str) -> Checkpoint | None:
        """Retrieve an isolated copy of the most recent verified checkpoint."""
        with self._lock:
            checkpoint = self.latest.get(research_id)
            if checkpoint is None:
                return None
            if not checkpoint.is_valid_hash():
                raise CheckpointIntegrityError(
                    f"checkpoint payload hash mismatch for research '{research_id}'"
                )
            return self._clone(checkpoint)

    def load_version(self, research_id: str, version: int) -> Checkpoint | None:
        """Retrieve a specific verified version if retained in history."""
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            return None
        with self._lock:
            for checkpoint in self.history.get(research_id, []):
                if checkpoint.version == version:
                    if not checkpoint.is_valid_hash():
                        raise CheckpointIntegrityError(
                            f"checkpoint payload hash mismatch for research '{research_id}'"
                        )
                    return self._clone(checkpoint)
            return None

    def rollback_to(self, research_id: str, phase: str) -> Checkpoint | None:
        """Point latest to the newest valid checkpoint at the requested phase."""
        with self._lock:
            for checkpoint in reversed(self.history.get(research_id, [])):
                if checkpoint.phase != phase:
                    continue
                if not checkpoint.is_valid_hash():
                    raise CheckpointIntegrityError(
                        f"checkpoint payload hash mismatch for research '{research_id}'"
                    )
                self.latest[research_id] = checkpoint
                return self._clone(checkpoint)
            return None

    def list_history(self, research_id: str) -> list[Checkpoint]:
        """Return isolated copies of all retained checkpoint history."""
        with self._lock:
            return [self._clone(item) for item in self.history.get(research_id, [])]

    def invalidate(self, research_id: str) -> None:
        """Clear cached and historical checkpoints for a research run."""
        with self._lock:
            self.latest.pop(research_id, None)
            self.history.pop(research_id, None)


__all__ = [
    "Checkpoint",
    "CheckpointIntegrityError",
    "CheckpointManager",
]
