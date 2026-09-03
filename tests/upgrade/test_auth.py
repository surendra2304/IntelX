import pytest
from intelx_upgrade.auth import validate_production_secret, AuthError
def test_secret_strength():
    with pytest.raises(AuthError): validate_production_secret("weak")
