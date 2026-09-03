from intelx_upgrade.citations import CitationValidator
def test_citation_ids():
    c=CitationValidator().validate("A [S:one] B", {"one"})
    assert c.valid and not c.missing
