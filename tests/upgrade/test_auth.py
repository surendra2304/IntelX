import pytest

from intelx_upgrade.auth import AuthError, validate_production_secret


def test_secret_strength():
    with pytest.raises(AuthError):
        validate_production_secret("weak")
