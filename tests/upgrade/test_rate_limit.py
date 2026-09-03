from intelx_upgrade.rate_limit import SlidingWindow
def test_limit():
    r=SlidingWindow(1,10)
    assert r.allow("x").allowed
    assert not r.allow("x").allowed
