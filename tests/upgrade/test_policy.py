from intelx_upgrade.policy import DomainPolicy, ResearchPolicy, PolicyViolation
def test_domain_allowlist():
    p=ResearchPolicy(DomainPolicy(allow_domains=frozenset({"example.com"})))
    assert p.validate_url("https://www.example.com/a")=="www.example.com"
    try: p.validate_url("https://evil.com")
    except PolicyViolation: pass
    else: raise AssertionError
