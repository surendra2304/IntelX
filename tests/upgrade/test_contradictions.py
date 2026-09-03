from intelx_upgrade.contradictions import ContradictionEngine
from intelx_upgrade.models import Claim
def test_conflict():
    a=Claim("a","the system is reliable","p",.8,("e1",),("s1",))
    b=Claim("b","the system is not reliable","p",.7,("e2",),("s2",))
    assert ContradictionEngine().detect([a,b])
