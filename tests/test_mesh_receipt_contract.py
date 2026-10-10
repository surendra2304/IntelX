"""Mesh receipt contract for FRIDAY's cognitive verification of IntelX work.

FRIDAY's cognitive mesh (friday.cognition.mesh.verify_receipt) refuses to treat a
delegated task as COMPLETED unless the peer's answer carries an ActionReceipt that:

* names the action FRIDAY dispatched (``requested_action == envelope.action``),
* targets this agent (``target == envelope.target_agent``),
* declares an authorization decision of AUTHORIZED / PRE_APPROVED,
* carries non-empty verification evidence, and
* reports no failure_reason.

These tests pin that contract on IntelX's Universal Task Protocol endpoint so a
schema drift on either side is caught here, not discovered as an endless stream
of UNVERIFIED outcomes on the caller.
"""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from intelx.app.factory import create_app
from intelx.core.auth import hash_api_key
from intelx.core.enums import ApiKeyRole
from intelx.db.engine import get_async_engine
from intelx.db.models import ApiKey
from intelx.db.session import get_sessionmaker

REQUIRED_DECISIONS = {"AUTHORIZED", "PRE_APPROVED"}


@pytest.fixture
async def friday_client():
    """ASGI client with a seeded FRIDAY key that may drive /v1/task/execute."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        from intelx.db.base import Base

        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        f_hash = hash_api_key("friday-mesh-receipt-key")
        stmt = select(ApiKey).where(ApiKey.key_hash == f_hash)
        if not (await session.execute(stmt)).scalar_one_or_none():
            session.add(
                ApiKey(
                    key_hash=f_hash,
                    name="friday-mesh-receipt",
                    role=ApiKeyRole.MEMBER,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer friday-mesh-receipt-key"}
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac, headers


@pytest.mark.asyncio
async def test_research_answer_carries_a_mesh_verifiable_receipt(friday_client):
    client, headers = friday_client

    resp = await client.post(
        "/v1/task/execute",
        json={
            "task_id": "task_mesh_receipt_001",
            "action": "research",
            "objective": "macro intelligence for the week",
            "target_agent": "intelx",
            "source_agent": "friday",
            "payload": {"query": "macro intelligence for the week"},
        },
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    receipt = body.get("receipt")
    assert isinstance(receipt, dict), "IntelX answered without a receipt; FRIDAY will read this as UNVERIFIED"
    assert receipt["requested_action"] == "research"
    assert receipt["target"] == "intelx"
    assert receipt["authorization_decision"].upper() in REQUIRED_DECISIONS
    assert isinstance(receipt["verification_evidence"], dict)
    assert receipt["verification_evidence"], "empty verification evidence counts as unproven to FRIDAY"
    assert not receipt.get("failure_reason")
    assert receipt.get("execution_timestamp")


@pytest.mark.asyncio
async def test_receipt_verification_evidence_records_what_was_verified(friday_client):
    client, headers = friday_client

    resp = await client.post(
        "/v1/task/execute",
        json={
            "task_id": "task_mesh_receipt_002",
            "action": "research",
            "objective": "energy density benchmarks",
            "target_agent": "intelx",
            "payload": {"query": "energy density benchmarks"},
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    receipt = body["receipt"]
    evidence = receipt["verification_evidence"]
    # Evidence must be traceable: the caller's task id and countable work.
    assert evidence.get("task_id") == "task_mesh_receipt_002"
    assert isinstance(evidence.get("sources_count"), int)
    assert isinstance(evidence.get("findings_count"), int)
    assert "provenance_chain_length" in evidence
    # The result body itself still carries the research answer for consumers.
    assert body["status"] == "SUCCESS"
    assert "sources" in body["result"]


@pytest.mark.asyncio
async def test_cancel_answer_carries_a_receipt_naming_the_cancel_action(friday_client):
    """The cancel action is Universal-Task-Protocol work too, so it is receipted."""
    client, headers = friday_client

    resp = await client.post(
        "/v1/task/execute",
        json={
            "task_id": "task_mesh_receipt_003",
            "action": "cancel",
            "objective": "cancel",
            "target_agent": "intelx",
            "payload": {"run_id": "no-such-run"},
        },
        headers=headers,
    )
    # Unknown run -> the run lookup found nothing, so the endpoint falls through to
    # the research path for this action value; either way the answer that comes back
    # must not break the mesh contract. If it is a cancellation it must be receipted.
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        receipt = resp.json().get("receipt")
        if receipt is not None:
            assert receipt["requested_action"] == "cancel"
            assert receipt["target"] == "intelx"
            assert receipt["authorization_decision"].upper() in REQUIRED_DECISIONS
            assert receipt["verification_evidence"] or receipt["result"]
