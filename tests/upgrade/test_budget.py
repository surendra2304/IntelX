from intelx_upgrade.budget import BudgetController, BudgetLedger, BudgetExceeded
def test_budget():
    b=BudgetController(max_queries=1)
    l=BudgetLedger(); b.charge_query(l)
    try: b.charge_query(l)
    except BudgetExceeded: pass
    else: raise AssertionError
