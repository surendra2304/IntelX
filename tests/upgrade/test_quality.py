from intelx_upgrade.models import Claim
from intelx_upgrade.quality import evaluate


def test_quality():
    c = Claim("c", "statement", "p", 0.9, ("e1", "e2"), ("s",))
    q = evaluate([c], {"c": ["e1", "e2"]}, lambda _: True)
    assert q.pass_gate
