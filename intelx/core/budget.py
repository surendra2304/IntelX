"""INTELX Durable Research Budget Ledger and Atomic Cost Controller."""

from __future__ import annotations

import asyncio
import math
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
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def reset(self) -> None:
        """Reset budget counters to initial state."""
        self.queries = 0
        self.fetches = 0
        self.sources = 0
        self.cost_usd = 0.0
        self.runtime_seconds = 0.0
        self.reserved_usd = 0.0
        self.status = "ACTIVE"
        self.updated_at = datetime.now(UTC)





def _non_negative_int(value: int, name: str) -> int:
    """Reject boolean, negative, or non-integer usage values."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _non_negative_number(value: float, name: str) -> float:
    """Reject negative and non-finite monetary or duration values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number")
    try:
        is_finite = math.isfinite(value)
    except OverflowError:
        is_finite = False
    if not is_finite or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


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
        self.max_queries = _non_negative_int(max_queries, "max_queries")
        self.max_fetches = _non_negative_int(max_fetches, "max_fetches")
        self.max_sources = _non_negative_int(max_sources, "max_sources")
        self.max_cost = _non_negative_number(max_cost, "max_cost")
        self.max_runtime_seconds = _non_negative_number(
            max_runtime_seconds, "max_runtime_seconds"
        )
        self._lock = asyncio.Lock()

    def charge_query(self, ledger: BudgetLedger, count: int = 1) -> None:
        """Charge query invocations against ledger."""
        count = _non_negative_int(count, "count")
        ledger.queries += count
        ledger.updated_at = datetime.now(UTC)
        self._check(ledger)

    def charge_fetch(self, ledger: BudgetLedger, count: int = 1) -> None:
        """Charge HTTP fetch operations against ledger."""
        count = _non_negative_int(count, "count")
        ledger.fetches += count
        ledger.updated_at = datetime.now(UTC)
        self._check(ledger)

    def charge_source(self, ledger: BudgetLedger, count: int = 1) -> None:
        """Charge ingested source documents against ledger."""
        count = _non_negative_int(count, "count")
        ledger.sources += count
        ledger.updated_at = datetime.now(UTC)
        self._check(ledger)

    def charge_cost(self, ledger: BudgetLedger, usd: float) -> None:
        """Charge USD model or search provider cost against ledger."""
        usd = _non_negative_number(usd, "usd")
        ledger.cost_usd += usd
        ledger.updated_at = datetime.now(UTC)
        self._check(ledger)

    def charge_runtime(self, ledger: BudgetLedger, seconds: float) -> None:
        """Accumulate execution elapsed runtime."""
        seconds = _non_negative_number(seconds, "seconds")
        ledger.runtime_seconds += seconds
        ledger.updated_at = datetime.now(UTC)
        self._check(ledger)

    async def reserve_budget(self, ledger: BudgetLedger, usd_estimate: float) -> None:
        """Atomically reserve financial budget before launching expensive parallel tasks."""
        usd_estimate = _non_negative_number(usd_estimate, "usd_estimate")
        async with self._lock:
            total = ledger.cost_usd + ledger.reserved_usd + usd_estimate
            if total > self.max_cost:
                raise BudgetExceeded(
                    f"budget reservation failed: (${total:.4f}) "
                    f"exceeds max (${self.max_cost:.4f})"
                )
            ledger.reserved_usd += usd_estimate
            ledger.updated_at = datetime.now(UTC)

    async def commit_reservation(
        self, ledger: BudgetLedger, reserved_usd: float, actual_usd: float
    ) -> None:
        """Commit actual expenditure and release unused reserved balance."""
        reserved_usd = _non_negative_number(reserved_usd, "reserved_usd")
        actual_usd = _non_negative_number(actual_usd, "actual_usd")
        async with self._lock:
            if reserved_usd > ledger.reserved_usd:
                raise ValueError("reserved_usd exceeds the outstanding reservation balance")
            ledger.reserved_usd = max(0.0, ledger.reserved_usd - reserved_usd)
            ledger.cost_usd += actual_usd
            ledger.updated_at = datetime.now(UTC)
            self._check(ledger)

    async def rollback_reservation(self, ledger: BudgetLedger, reserved_usd: float) -> None:
        """Safely release reserved budget when an operation is cancelled or aborted."""
        reserved_usd = _non_negative_number(reserved_usd, "reserved_usd")
        async with self._lock:
            if reserved_usd > ledger.reserved_usd:
                raise ValueError("reserved_usd exceeds the outstanding reservation balance")
            ledger.reserved_usd = max(0.0, ledger.reserved_usd - reserved_usd)
            ledger.updated_at = datetime.now(UTC)

    def remaining_budget(self, ledger: BudgetLedger) -> dict[str, float]:
        """Calculate remaining resource quotas and available budget."""
        return {
            "remaining_queries": max(0, self.max_queries - ledger.queries),
            "remaining_fetches": max(0, self.max_fetches - ledger.fetches),
            "remaining_sources": max(0, self.max_sources - ledger.sources),
            "remaining_cost_usd": round(
                max(0.0, self.max_cost - (ledger.cost_usd + ledger.reserved_usd)), 6
            ),
            "remaining_runtime_seconds": round(
                max(0.0, self.max_runtime_seconds - ledger.runtime_seconds), 2
            ),
        }

    def is_near_exhaustion(
        self, ledger: BudgetLedger, threshold: float = 0.85
    ) -> tuple[bool, list[str]]:
        """Check if any budget dimension has reached or exceeded the danger threshold."""
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold)
            or not 0.0 <= threshold <= 1.0
        ):
            raise ValueError("threshold must be finite and between 0.0 and 1.0")
        warnings: list[str] = []
        if ledger.queries >= self.max_queries * threshold:
            warnings.append(f"queries at {ledger.queries}/{self.max_queries}")
        if ledger.fetches >= self.max_fetches * threshold:
            warnings.append(f"fetches at {ledger.fetches}/{self.max_fetches}")
        if ledger.sources >= self.max_sources * threshold:
            warnings.append(f"sources at {ledger.sources}/{self.max_sources}")
        if (ledger.cost_usd + ledger.reserved_usd) >= self.max_cost * threshold:
            warnings.append(
                f"cost at ${(ledger.cost_usd + ledger.reserved_usd):.2f}/${self.max_cost:.2f}"
            )
        if ledger.runtime_seconds >= self.max_runtime_seconds * threshold:
            warnings.append(
                f"runtime at {ledger.runtime_seconds:.1f}s/{self.max_runtime_seconds:.1f}s"
            )
        return len(warnings) > 0, warnings

    def _check(self, ledger: BudgetLedger) -> None:
        """Check all ceilings and fail closed if exceeded."""
        if ledger.queries > self.max_queries:
            raise BudgetExceeded(
                f"research query limit exhausted: {ledger.queries} > {self.max_queries}"
            )
        if ledger.fetches > self.max_fetches:
            raise BudgetExceeded(
                f"research fetch limit exhausted: {ledger.fetches} > {self.max_fetches}"
            )
        if ledger.sources > self.max_sources:
            raise BudgetExceeded(
                f"research source limit exhausted: {ledger.sources} > {self.max_sources}"
            )
        if ledger.cost_usd > self.max_cost:
            raise BudgetExceeded(
                f"research budget exhausted: ${ledger.cost_usd:.4f} > ${self.max_cost:.4f}"
            )
        if ledger.runtime_seconds > self.max_runtime_seconds:
            raise BudgetExceeded(
                f"research time limit exhausted: {ledger.runtime_seconds:.1f}s > {self.max_runtime_seconds:.1f}s"
            )


__all__ = [
    "BudgetExceeded",
    "BudgetLedger",
    "BudgetController",
]
