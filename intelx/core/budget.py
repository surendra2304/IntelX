"""INTELX Durable Research Budget Ledger and Atomic Cost Controller."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class BudgetExceeded(RuntimeError):
    """Raised when research execution exceeds allocated resource or cost limits."""


@dataclass(slots=True)
class BudgetLedger:
    """In-memory and persistent tracker for resource and financial budget usage."""

    tenant_id: str = "default"
    research_id: str = ""
    queries: int = 0
    fetches: int = 0
    sources: int = 0
    cost_usd: float = 0.0
    runtime_seconds: float = 0.0
    reserved_usd: float = 0.0
    status: str = "ACTIVE"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert ledger metrics to dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "research_id": self.research_id,
            "queries": self.queries,
            "fetches": self.fetches,
            "sources": self.sources,
            "cost_usd": round(self.cost_usd, 6),
            "runtime_seconds": round(self.runtime_seconds, 2),
            "reserved_usd": round(self.reserved_usd, 6),
            "status": self.status,
        }


class BudgetController:
    """Enforces atomic resource limits and budget ceilings during research execution."""

    def __init__(
        self,
        max_queries: int = 40,
        max_fetches: int = 60,
        max_sources: int = 50,
        max_cost: float = 10.0,
        max_runtime_seconds: float = 900.0,
    ) -> None:
        self.max_queries = max_queries
        self.max_fetches = max_fetches
        self.max_sources = max_sources
        self.max_cost = max_cost
        self.max_runtime_seconds = max_runtime_seconds
        self._lock = asyncio.Lock()

    def charge_query(self, ledger: BudgetLedger, count: int = 1) -> None:
        """Charge query invocations against ledger."""
        ledger.queries += count
        ledger.updated_at = datetime.now(UTC)
        self._check(ledger)

    def charge_fetch(self, ledger: BudgetLedger, count: int = 1) -> None:
        """Charge HTTP fetch operations against ledger."""
        ledger.fetches += count
        ledger.updated_at = datetime.now(UTC)
        self._check(ledger)

    def charge_source(self, ledger: BudgetLedger, count: int = 1) -> None:
        """Charge ingested source documents against ledger."""
        ledger.sources += count
        ledger.updated_at = datetime.now(UTC)
        self._check(ledger)

    def charge_cost(self, ledger: BudgetLedger, usd: float) -> None:
        """Charge USD model or search provider cost against ledger."""
        ledger.cost_usd += max(0.0, usd)
        ledger.updated_at = datetime.now(UTC)
        self._check(ledger)

    def charge_runtime(self, ledger: BudgetLedger, seconds: float) -> None:
        """Accumulate execution elapsed runtime."""
        ledger.runtime_seconds += max(0.0, seconds)
        ledger.updated_at = datetime.now(UTC)
        self._check(ledger)

    async def reserve_budget(self, ledger: BudgetLedger, usd_estimate: float) -> None:
        """Atomically reserve financial budget before launching expensive parallel tasks."""
        async with self._lock:
            if (ledger.cost_usd + ledger.reserved_usd + usd_estimate) > self.max_cost:
                raise BudgetExceeded(
                    f"budget reservation failed: (${ledger.cost_usd + ledger.reserved_usd + usd_estimate:.4f}) "
                    f"exceeds max (${self.max_cost:.4f})"
                )
            ledger.reserved_usd += usd_estimate

    async def commit_reservation(self, ledger: BudgetLedger, reserved_usd: float, actual_usd: float) -> None:
        """Commit actual expenditure and release unused reserved balance."""
        async with self._lock:
            ledger.reserved_usd = max(0.0, ledger.reserved_usd - reserved_usd)
            ledger.cost_usd += max(0.0, actual_usd)
            self._check(ledger)

    def _check(self, l: BudgetLedger) -> None:
        """Check all ceilings and fail closed if exceeded."""
        if l.queries > self.max_queries:
            raise BudgetExceeded(f"research query limit exhausted: {l.queries} > {self.max_queries}")
        if l.fetches > self.max_fetches:
            raise BudgetExceeded(f"research fetch limit exhausted: {l.fetches} > {self.max_fetches}")
        if l.sources > self.max_sources:
            raise BudgetExceeded(f"research source limit exhausted: {l.sources} > {self.max_sources}")
        if l.cost_usd > self.max_cost:
            raise BudgetExceeded(f"research budget exhausted: ${l.cost_usd:.4f} > ${self.max_cost:.4f}")
        if l.runtime_seconds > self.max_runtime_seconds:
            raise BudgetExceeded(
                f"research time limit exhausted: {l.runtime_seconds:.1f}s > {self.max_runtime_seconds:.1f}s"
            )
