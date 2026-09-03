from intelx_upgrade.dedupe import IndependenceAnalyzer
def test_independence():
    x=IndependenceAnalyzer()
    assert x.likely_syndicated(["same text","same text"])
    assert len(x.independent_domains(["https://a.com/x","https://b.com/y"]))==2
