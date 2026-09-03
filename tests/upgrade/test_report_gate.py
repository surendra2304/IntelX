from intelx_upgrade.report_gate import FinalReportGate
def test_citation_gate():
    g=FinalReportGate().check("fact [S:a]",{"a":True},[])
    assert g.complete
