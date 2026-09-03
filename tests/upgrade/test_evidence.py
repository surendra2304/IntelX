from intelx_upgrade.models import Evidence
def test_exact_span():
    e=Evidence("e","s","c","hello",1,6)
    assert e.validate_against("xhello world")
