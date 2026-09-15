import pytest

from intelx_upgrade.fetch_guard import SSRFBlocked, safe_target
from intelx_upgrade.policy import DomainPolicy, ResearchPolicy


def test_loopback_block():
    p = ResearchPolicy(DomainPolicy())
    with pytest.raises(SSRFBlocked):
        safe_target("http://127.0.0.1", p)
