from __future__ import annotations
from dataclasses import dataclass

@dataclass(slots=True)
class BudgetLedger:
    queries: int = 0
    fetches: int = 0
    sources: int = 0
    cost_usd: float = 0.0
    runtime_seconds: float = 0.0

class BudgetExceeded(RuntimeError): pass

class BudgetController:
    def __init__(self, max_queries=40, max_fetches=60, max_sources=50, max_cost=10.0):
        self.max_queries=max_queries; self.max_fetches=max_fetches
        self.max_sources=max_sources; self.max_cost=max_cost

    def charge_query(self, ledger): ledger.queries += 1; self._check(ledger)
    def charge_fetch(self, ledger): ledger.fetches += 1; self._check(ledger)
    def charge_source(self, ledger): ledger.sources += 1; self._check(ledger)
    def charge_cost(self, ledger, usd): ledger.cost_usd += max(0.0, usd); self._check(ledger)

    def _check(self, l):
        if l.queries > self.max_queries or l.fetches > self.max_fetches or l.sources > self.max_sources or l.cost_usd > self.max_cost:
            raise BudgetExceeded("research budget exhausted")
