"""Tests for Continuous Research Subscriptions API (intelx/api/v1/subscriptions.py)."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from intelx.api.v1.subscriptions import clear_subscriptions_for_testing
from intelx.app.factory import create_app
from intelx.core.auth import Principal, get_current_principal


@pytest_asyncio.fixture
async def sub_clients() -> AsyncGenerator[tuple[AsyncClient, AsyncClient], None]:
    """Provide two clients: tenant_a client and tenant_b client with dependency overrides."""
    clear_subscriptions_for_testing()

    app_a = create_app()
    app_b = create_app()

    # Tenant A principal (member, tenant_a)
    p_a = Principal(
        actor_id="user_alice",
        tenant_id="tenant_a",
        roles=("member",),
        scopes=frozenset({"research:read", "research:write"}),
    )
    app_a.dependency_overrides[get_current_principal] = lambda: p_a

    # Tenant B principal (member, tenant_b)
    p_b = Principal(
        actor_id="user_bob",
        tenant_id="tenant_b",
        roles=("member",),
        scopes=frozenset({"research:read", "research:write"}),
    )
    app_b.dependency_overrides[get_current_principal] = lambda: p_b

    transport_a = ASGITransport(app=app_a)
    transport_b = ASGITransport(app=app_b)

    async with (
        AsyncClient(transport=transport_a, base_url="http://testserver") as client_a,
        AsyncClient(transport=transport_b, base_url="http://testserver") as client_b,
    ):
        yield client_a, client_b

    clear_subscriptions_for_testing()


@pytest.mark.asyncio
async def test_subscription_lifecycle(sub_clients: tuple[AsyncClient, AsyncClient]):
    """Test full CRUD lifecycle: create, list, get, pause, resume, delete."""
    client_a, _ = sub_clients

    # 1. Create subscription
    create_payload = {
        "objective": "Track semiconductor supply chain disruptions and Fab capacity",
        "schedule_cron": "0 8 * * 1-5",
        "search_scope": {"domain": "semiconductors", "depth": "standard"},
        "budget_usd": 10.0,
        "notification_webhook": "https://example.com/webhooks/intelx",
    }
    res_create = await client_a.post("/api/v1/subscriptions", json=create_payload)
    assert res_create.status_code == 201
    sub = res_create.json()
    sub_id = sub["id"]
    assert sub_id.startswith("sub_")
    assert sub["tenant_id"] == "tenant_a"
    assert sub["principal_id"] == "user_alice"
    assert sub["objective"] == create_payload["objective"]
    assert sub["status"] == "ACTIVE"
    assert sub["schedule_cron"] == "0 8 * * 1-5"

    # 2. List subscriptions for tenant A
    res_list = await client_a.get("/api/v1/subscriptions")
    assert res_list.status_code == 200
    items = res_list.json()
    assert len(items) == 1
    assert items[0]["id"] == sub_id

    # 3. Get single subscription
    res_get = await client_a.get(f"/api/v1/subscriptions/{sub_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == sub_id

    # 4. Pause subscription
    res_pause = await client_a.post(f"/api/v1/subscriptions/{sub_id}/pause")
    assert res_pause.status_code == 200
    assert res_pause.json()["status"] == "PAUSED"

    # 5. Resume subscription
    res_resume = await client_a.post(f"/api/v1/subscriptions/{sub_id}/resume")
    assert res_resume.status_code == 200
    assert res_resume.json()["status"] == "ACTIVE"

    # 6. Delete subscription
    res_del = await client_a.delete(f"/api/v1/subscriptions/{sub_id}")
    assert res_del.status_code == 204

    # 7. Subsequent GET returns 404
    res_get_deleted = await client_a.get(f"/api/v1/subscriptions/{sub_id}")
    assert res_get_deleted.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_subscription_isolation(sub_clients: tuple[AsyncClient, AsyncClient]):
    """Verify that tenant B cannot read, pause, resume, or delete tenant A's subscription."""
    client_a, client_b = sub_clients

    # Tenant A creates subscription
    res = await client_a.post(
        "/api/v1/subscriptions",
        json={"objective": "Confidential M&A Intelligence for Tenant A"},
    )
    assert res.status_code == 201
    sub_id = res.json()["id"]

    # Tenant B lists subscriptions -> should be empty
    res_b_list = await client_b.get("/api/v1/subscriptions")
    assert res_b_list.status_code == 200
    assert len(res_b_list.json()) == 0

    # Tenant B tries to get Tenant A's subscription -> 403 Forbidden
    res_b_get = await client_b.get(f"/api/v1/subscriptions/{sub_id}")
    assert res_b_get.status_code == 403

    # Tenant B tries to pause Tenant A's subscription -> 403 Forbidden
    res_b_pause = await client_b.post(f"/api/v1/subscriptions/{sub_id}/pause")
    assert res_b_pause.status_code == 403

    # Tenant B tries to resume Tenant A's subscription -> 403 Forbidden
    res_b_resume = await client_b.post(f"/api/v1/subscriptions/{sub_id}/resume")
    assert res_b_resume.status_code == 403

    # Tenant B tries to delete Tenant A's subscription -> 403 Forbidden
    res_b_del = await client_b.delete(f"/api/v1/subscriptions/{sub_id}")
    assert res_b_del.status_code == 403


@pytest.mark.asyncio
async def test_subscription_not_found(sub_clients: tuple[AsyncClient, AsyncClient]):
    """Verify 404 responses for non-existent subscription IDs."""
    client_a, _ = sub_clients
    assert (await client_a.get("/api/v1/subscriptions/sub_nonexistent")).status_code == 404
    assert (await client_a.post("/api/v1/subscriptions/sub_nonexistent/pause")).status_code == 404
    assert (await client_a.post("/api/v1/subscriptions/sub_nonexistent/resume")).status_code == 404
    assert (await client_a.delete("/api/v1/subscriptions/sub_nonexistent")).status_code == 404
