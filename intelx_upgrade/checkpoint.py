from __future__ import annotations
from dataclasses import dataclass
import time

@dataclass(frozen=True, slots=True)
class Checkpoint:
    research_id: str
    phase: str
    version: int
    state_hash: str
    created_at: float = time.time()

class CheckpointManager:
    def __init__(self): self.latest={}
    def save(self, checkpoint): self.latest[checkpoint.research_id]=checkpoint
    def load(self, research_id): return self.latest.get(research_id)
