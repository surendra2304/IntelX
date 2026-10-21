"""Tests for Tenant Boundary Security and Sentinel Policy Interoperability."""

import httpx
import pytest

from intelx.core.settings import Settings
from intelx.core.tenant import (
    TenantBoundary,
    TenantContext,
    TenantViolation,
    admin_principal,
    get_current_principal,
    member_principal,
)
from intelx.integrations.sentinel_policy import SentinelSecurityClient


def test_principal_and_tenant_boundary_enforcement():
    """Verify principal scopes, roles, and tenant boundary enforcement."""
    boundary = TenantBoundary()

    admin = admin_principal()
    assert admin.has_role("admin") is True
    assert admin.has_scope("anything") is True

    member = member_principal("tenant-a", "user-1", scopes=["research:read"])
    assert member.has_role("member") is True
    assert member.has_role("admin") is False
    assert member.has_scope("research:read") is True
    assert member.has_scope("research:delete") is False

    # Within same tenant: allowed
    boundary.require(member, "tenant-a")
    boundary.require_scope(member, "research:read")

    # Cross-tenant access: rejected
    with pytest.raises(TenantViolation, match="cross-tenant access denied"):
        boundary.require(member, "tenant-b")

    # Missing scope: rejected
    with pytest.raises(TenantViolation, match="scope denied"):
        boundary.require_scope(member, "research:delete")

    # Wildcard admin permitted across tenants
    boundary.require(admin, "tenant-b")
    boundary.require_scope(admin, "any:scope")


def test_tenant_context_ambient_scoping():
    """Verify TenantContext sets and cleans up ambient principal via contextvars."""
    assert get_current_principal() is None

    p = member_principal("tenant-corp", "analyst-42")
    with TenantContext(p) as active_principal:
        assert active_principal == p
        assert get_current_principal() == p

    assert get_current_principal() is None


@pytest.mark.asyncio
async def test_sentinel_client_mock_and_live_authorization(monkeypatch):
    """Verify Sentinel client authorization and incident reporting."""
    # 1. Mock mode
    client_mock = SentinelSecurityClient()
    authorized_mock = await client_mock.authorize_connector_action(
        connector_kind="web_fetch",
        target_location="https://trusted.org",
        tenant_id="tenant-1",
        actor_id="agent-intelx",
    )
    assert authorized_mock is True

    # 2. Live HTTP mode with transport
    def mock_sentinel_handler(request: httpx.Request) -> httpx.Response:
        if "/v1/policy/authorize" in str(request.url):
            return httpx.Response(200, json={"allowed": True})
        elif "/v1/incidents" in str(request.url):
            return httpx.Response(201, json={"incident_id": "inc-999"})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_sentinel_handler)
    settings = Settings(_env_file=None, MOCK_MODE=False)
    from intelx.integrations import sentinel_policy

    monkeypatch.setattr(sentinel_policy, "get_settings", lambda: settings)

    client_live = SentinelSecurityClient(
        base_url="http://sentinel:8000",
        api_key="sentinel-secret-key-32chars-minimum-token",
        transport=transport,
    )

    auth_live = await client_live.authorize_connector_action(
        connector_kind="web_fetch",
        target_location="https://untrusted.com",
        tenant_id="tenant-corp",
        actor_id="intelx-crawler",
    )
    assert auth_live is True

    incident_result = await client_live.report_security_incident(
        incident_type="SSRF_ATTEMPT",
        details={"ip": "169.254.169.254", "url": "http://169.254.169.254/latest/meta-data"},
        tenant_id="tenant-corp",
    )
    assert incident_result["status"] == "reported"
    assert incident_result["response"]["incident_id"] == "inc-999"
    assert len(client_live.incident_log) == 1
