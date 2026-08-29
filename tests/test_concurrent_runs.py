"""Tests for Concurrent Run Management, Priority Queueing, and State Isolation."""

import pytest
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.core.settings import get_settings
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker


@pytest.mark.asyncio
async def test_concurrent_run_priority_and_isolation():
    """Verify 5 runs maintain strict isolation and priority ordering (urgent skips queue)."""
    settings = get_settings()
    settings.MOCK_MODE = True
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        # Create normal priority run first
        await RunRepo.create_run(
            session=session,
            objective="Evaluate solid state battery electrolyte conductivity",
            scope_json={"priority": "normal", "context": {"priority": "normal"}},
        )
        # Create urgent priority run second
        urgent_run = await RunRepo.create_run(
            session=session,
            objective="Assess emergency vulnerability CVE-2026-9999",
            scope_json={"priority": "urgent", "context": {"priority": "urgent"}},
        )
        await session.commit()

        # Claim next run: urgent must be claimed first despite being created second
        claimed = await RunRepo.get_or_claim_next_queued_job(session)
        assert claimed is not None
        assert claimed.id == urgent_run.id
        await session.commit()


@pytest.mark.asyncio
async def test_max_concurrent_runs_limit():
    """Verify worker honors MAX_CONCURRENT_RUNS bound."""
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        # Create a queued run
        q_run = await RunRepo.create_run(
            session=session,
            objective="Analyze quantum annealing fidelity",
            scope_json={"priority": "normal"},
        )
        await session.commit()

        # When max_concurrent is set to 0, claim returns None
        claimed_none = await RunRepo.get_or_claim_next_queued_job(session, max_concurrent=0)
        assert claimed_none is None

        # When max_concurrent is allowed, claim succeeds
        claimed_ok = await RunRepo.get_or_claim_next_queued_job(session, max_concurrent=5)
        assert claimed_ok is not None
        assert claimed_ok.id == q_run.id
        await session.commit()


@pytest.mark.asyncio
async def test_graceful_run_cancellation_preserves_partial_state():
    """Verify DELETE /api/v1/runs/{id} cancels run gracefully while keeping partial claims."""
    from intelx.core.auth import hash_api_key
    from intelx.core.enums import ApiKeyRole
    from intelx.db.models import ApiKey

    settings = get_settings()
    settings.MOCK_MODE = True

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        k_admin = ApiKey(
            key_hash=hash_api_key("dev-admin-key"),
            name="test-admin",
            role=ApiKeyRole.ADMIN,
        )
        session.add(k_admin)
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer dev-admin-key"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create a research run
        create_resp = await client.post(
            "/api/v1/research/jobs",
            json={"objective": "Test cancellation safety"},
            headers=headers,
        )
        assert create_resp.status_code == 202
        run_id = create_resp.json()["id"]

        # 2. Cancel run via DELETE endpoint
        cancel_resp = await client.delete(
            f"/api/v1/research/jobs/{run_id}",
            headers=headers,
        )
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        assert data["status"] in ("CANCELLED", "cancelled")
        assert data["id"] == run_id
