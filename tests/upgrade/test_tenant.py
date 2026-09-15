import pytest

from intelx_upgrade.tenant import Principal, TenantBoundary, TenantViolation


def test_tenant():
    with pytest.raises(TenantViolation):
        TenantBoundary().require(Principal("a", "u"), "b")
