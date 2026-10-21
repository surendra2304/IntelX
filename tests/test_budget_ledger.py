"""Tests for Durable Research Budget Ledger and Cost Controller."""

import pytest

from intelx.core.budget import BudgetController, BudgetExceeded, BudgetLedger


def test_budget_ledger_initialization_and_serialization():
    """Verify default values, serialization, and reset behavior."""
    ledger = BudgetLedger(tenant_id="tenant-alpha", research_id="run-101")
    assert ledger.queries == 0
    assert ledger.fetches == 0
    assert ledger.sources == 0
    assert ledger.cost_usd == 0.0
    assert ledger.reserved_usd == 0.0

    d = ledger.to_dict()
    assert d["tenant_id"] == "tenant-alpha"
    assert d["research_id"] == "run-101"
    assert d["status"] == "ACTIVE"

    ledger.queries = 5
    ledger.cost_usd = 1.25
    ledger.reset()
    assert ledger.queries == 0
    assert ledger.cost_usd == 0.0


def test_budget_controller_charging_and_limits():
    """Verify charging updates counters and enforces limits."""
    controller = BudgetController(
        max_queries=5,
        max_fetches=5,
        max_sources=3,
        max_cost=2.0,
        max_runtime_seconds=10.0,
    )
    ledger = BudgetLedger()

    controller.charge_query(ledger, 3)
    assert ledger.queries == 3

    controller.charge_fetch(ledger, 2)
    assert ledger.fetches == 2

    controller.charge_source(ledger, 2)
    assert ledger.sources == 2

    controller.charge_cost(ledger, 0.50)
    assert ledger.cost_usd == 0.50

    controller.charge_runtime(ledger, 4.0)
    assert ledger.runtime_seconds == 4.0

    # Exceed queries limit
    with pytest.raises(BudgetExceeded, match="query limit exhausted"):
        controller.charge_query(ledger, 3)  # total 6 > 5

    ledger.queries = 0
    # Exceed fetches limit
    with pytest.raises(BudgetExceeded, match="fetch limit exhausted"):
        controller.charge_fetch(ledger, 4)  # total 6 > 5

    ledger.fetches = 0
    # Exceed sources limit
    with pytest.raises(BudgetExceeded, match="source limit exhausted"):
        controller.charge_source(ledger, 2)  # total 4 > 3

    ledger.sources = 0
    # Exceed cost limit
    with pytest.raises(BudgetExceeded, match="budget exhausted"):
        controller.charge_cost(ledger, 2.0)  # total 2.5 > 2.0

    ledger.cost_usd = 0.0
    # Exceed runtime limit
    with pytest.raises(BudgetExceeded, match="time limit exhausted"):
        controller.charge_runtime(ledger, 10.0)  # total 14.0 > 10.0


@pytest.mark.asyncio
async def test_budget_reservation_and_commit():
    """Verify atomic reservation, commitment, and rollback."""
    controller = BudgetController(max_cost=5.0)
    ledger = BudgetLedger()

    # Successful reservation
    await controller.reserve_budget(ledger, 2.0)
    assert ledger.reserved_usd == 2.0

    # Second reservation exceeding total max
    with pytest.raises(BudgetExceeded, match="budget reservation failed"):
        await controller.reserve_budget(ledger, 4.0)  # 2.0 + 4.0 > 5.0

    # Commit reservation with lower actual cost
    await controller.commit_reservation(ledger, reserved_usd=2.0, actual_usd=1.20)
    assert ledger.reserved_usd == 0.0
    assert ledger.cost_usd == 1.20

    # Rollback reservation
    await controller.reserve_budget(ledger, 1.50)
    assert ledger.reserved_usd == 1.50
    await controller.rollback_reservation(ledger, reserved_usd=1.50)
    assert ledger.reserved_usd == 0.0


def test_budget_controller_rejects_negative_and_nonfinite_charges():
    controller = BudgetController()
    ledger = BudgetLedger()

    with pytest.raises(ValueError, match="count"):
        controller.charge_query(ledger, count=-1)
    with pytest.raises(ValueError, match="count"):
        controller.charge_fetch(ledger, count=True)
    with pytest.raises(ValueError, match="usd"):
        controller.charge_cost(ledger, -0.01)
    with pytest.raises(ValueError, match="usd"):
        controller.charge_cost(ledger, float("nan"))
    with pytest.raises(ValueError, match="seconds"):
        controller.charge_runtime(ledger, float("inf"))

    assert ledger.queries == 0
    assert ledger.fetches == 0
    assert ledger.cost_usd == 0.0
    assert ledger.runtime_seconds == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_queries": -1},
        {"max_fetches": True},
        {"max_sources": 1.5},
        {"max_cost": float("inf")},
        {"max_runtime_seconds": float("nan")},
    ],
)
def test_budget_controller_rejects_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        BudgetController(**kwargs)


@pytest.mark.asyncio
async def test_budget_reservations_reject_invalid_values_and_overrelease():
    controller = BudgetController(max_cost=5.0)
    ledger = BudgetLedger()

    with pytest.raises(ValueError, match="usd_estimate"):
        await controller.reserve_budget(ledger, -1.0)
    await controller.reserve_budget(ledger, 1.0)

    with pytest.raises(ValueError, match="outstanding reservation"):
        await controller.commit_reservation(ledger, reserved_usd=1.1, actual_usd=0.5)
    with pytest.raises(ValueError, match="outstanding reservation"):
        await controller.rollback_reservation(ledger, reserved_usd=2.0)
    with pytest.raises(ValueError, match="actual_usd"):
        await controller.commit_reservation(ledger, reserved_usd=0.0, actual_usd=float("nan"))

    assert ledger.reserved_usd == 1.0
    assert ledger.cost_usd == 0.0


def test_near_exhaustion_rejects_invalid_threshold():
    controller = BudgetController()
    with pytest.raises(ValueError, match="threshold"):
        controller.is_near_exhaustion(BudgetLedger(), threshold=1.1)


def test_remaining_budget_and_near_exhaustion():
    """Verify calculation of remaining quotas and warning detection."""
    controller = BudgetController(
        max_queries=10,
        max_fetches=10,
        max_sources=10,
        max_cost=10.0,
        max_runtime_seconds=100.0,
    )
    ledger = BudgetLedger(queries=8, fetches=9, sources=2, cost_usd=8.6, runtime_seconds=50.0)

    rem = controller.remaining_budget(ledger)
    assert rem["remaining_queries"] == 2
    assert rem["remaining_fetches"] == 1
    assert rem["remaining_cost_usd"] == 1.4
    assert rem["remaining_runtime_seconds"] == 50.0

    is_warning, warnings = controller.is_near_exhaustion(ledger, threshold=0.80)
    assert is_warning is True
    assert any("fetches at 9/10" in w for w in warnings)
    assert any("cost at $8.60/$10.00" in w for w in warnings)
