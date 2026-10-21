"""Tests for Ecosystem Mesh Peer Communications (_dispatch_external_research)."""

from unittest.mock import AsyncMock, patch

import pytest

from intelx.orchestration.engine import _dispatch_external_research


@pytest.mark.asyncio
async def test_dispatch_external_research_includes_all_peers():
    """Verify _dispatch_external_research invokes Memora, Futuris, StrateX, and Cortex."""
    with (
        patch(
            "intelx.integrations.memora_context.MemoraMemoryClient.publish_research_handoff",
            new_callable=AsyncMock,
        ) as mock_memora,
        patch(
            "intelx.integrations.futuris_context.FuturisContextProvider.notify_futuris_research_relevant",
            new_callable=AsyncMock,
        ) as mock_futuris,
        patch(
            "intelx.integrations.stratex_context.StratexConnector.notify_stratex_trade_signal",
            new_callable=AsyncMock,
        ) as mock_stratex,
        patch(
            "intelx.integrations.cortex_context.CortexConnector.notify_cortex_lead_intel",
            new_callable=AsyncMock,
        ) as mock_cortex,
    ):
        mock_memora.return_value = {"status": "stored", "memory_id": "mem-1"}
        mock_futuris.return_value = {"status": "delivered", "event": "research_finding_relevant"}
        mock_stratex.return_value = {"status": "delivered", "event": "research_trade_signal"}
        mock_cortex.return_value = {"status": "delivered", "event": "website_lead_intel"}

        outcomes = await _dispatch_external_research(
            run_id="run-mesh-001",
            objective="Evaluate new enterprise automation framework",
            finding_text="Enterprise automation reduces operational overhead by 40%.",
            domain="general",
            evidence_count=5,
            claims_count=10,
            tags=["intelx", "research", "general"],
            extra_context={
                "findings": [{"conclusion": "Enterprise automation reduces operational overhead."}]
            },
            confidence=0.88,
        )

        assert "Memora" in outcomes
        assert "Futuris" in outcomes
        assert "StrateX" in outcomes
        assert "Cortex" in outcomes

        assert outcomes["Memora"]["status"] == "stored"
        assert outcomes["Futuris"]["status"] == "delivered"
        assert outcomes["StrateX"]["status"] == "delivered"
        assert outcomes["Cortex"]["status"] == "delivered"

        mock_memora.assert_awaited_once()
        mock_futuris.assert_awaited_once()
        mock_stratex.assert_awaited_once()
        mock_cortex.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_external_research_fault_isolation():
    """Verify one failing peer does not prevent deliveries to remaining peers."""
    with (
        patch(
            "intelx.integrations.memora_context.MemoraMemoryClient.publish_research_handoff",
            new_callable=AsyncMock,
        ) as mock_memora,
        patch(
            "intelx.integrations.futuris_context.FuturisContextProvider.notify_futuris_research_relevant",
            new_callable=AsyncMock,
        ) as mock_futuris,
        patch(
            "intelx.integrations.stratex_context.StratexConnector.notify_stratex_trade_signal",
            new_callable=AsyncMock,
        ) as mock_stratex,
        patch(
            "intelx.integrations.cortex_context.CortexConnector.notify_cortex_lead_intel",
            new_callable=AsyncMock,
        ) as mock_cortex,
    ):
        mock_memora.return_value = {"status": "stored"}
        mock_futuris.side_effect = RuntimeError("Futuris connection timeout")
        mock_stratex.return_value = {"status": "delivered"}
        mock_cortex.return_value = {"status": "delivered"}

        outcomes = await _dispatch_external_research(
            run_id="run-mesh-002",
            objective="Market trend analysis",
            finding_text="Market shift detected.",
            domain="market",
            evidence_count=2,
            claims_count=4,
            tags=["intelx", "market"],
        )

        assert outcomes["Memora"]["status"] == "stored"
        assert outcomes["Futuris"]["status"] == "error"
        assert outcomes["Futuris"]["error"] == "RuntimeError"
        assert outcomes["StrateX"]["status"] == "delivered"
        assert outcomes["Cortex"]["status"] == "delivered"
