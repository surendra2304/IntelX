from intelx_upgrade.anti_corruption import redact
def test_redact():
    x=redact({"api_key":"secret","ok":"value"})
    assert x["api_key"]=="[REDACTED]" and x["ok"]=="value"
