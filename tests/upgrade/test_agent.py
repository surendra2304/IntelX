from intelx_upgrade.research_agent import EvidenceFirstAgent
from intelx_upgrade.models import *
def test_agent_needs_plan():
    i=ResearchIdentity("t","a","r","c"); s=ResearchState(i,"q",ResearchStatus.SEARCHING,None)
    assert EvidenceFirstAgent().decide(s).next_status==ResearchStatus.PLANNING
