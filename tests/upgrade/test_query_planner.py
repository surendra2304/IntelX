from intelx_upgrade.query_planner import QueryPortfolioPlanner
def test_portfolio():
    q=QueryPortfolioPlanner().build("p","what are battery density trends")
    assert len(q)>=5 and len({x.purpose for x in q})>=4
