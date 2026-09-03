from intelx_upgrade.models import *
from intelx_upgrade.research import ResearchController
def test_transition():
    i=ResearchIdentity("t","a","r","c")
    s=ResearchState(i,"q",ResearchStatus.QUEUED,None)
    s=ResearchController().transition(s,ResearchStatus.PLANNING)
    assert s.status==ResearchStatus.PLANNING
