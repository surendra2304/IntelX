from intelx_upgrade.quality import evaluate
from intelx_upgrade.models import Claim
def test_quality():
    c=Claim("c","statement","p",.9,("e1","e2"),("s",))
    q=evaluate([c],{"c":["e1","e2"]},lambda _: True)
    assert q.pass_gate
