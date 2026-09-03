from __future__ import annotations
from dataclasses import dataclass
import time

@dataclass(frozen=True, slots=True)
class ResearchMetric:
    tenant_id: str
    research_id: str
    phase: str
    duration_seconds: float
    source_count: int
    evidence_count: int
    claim_count: int
    cost_usd: float
    outcome: str

class MetricsSink:
    def record(self, metric: ResearchMetric): raise NotImplementedError

class InMemoryMetrics(MetricsSink):
    def __init__(self): self.items=[]
    def record(self, metric): self.items.append(metric)
