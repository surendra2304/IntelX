from intelx_upgrade.budget import BudgetController, BudgetExceeded, BudgetLedger


def test_budget():
    b = BudgetController(max_queries=1)
    ledger = BudgetLedger()
    b.charge_query(ledger)
    try:
        b.charge_query(ledger)
    except BudgetExceeded:
        pass
    else:
        raise AssertionError
