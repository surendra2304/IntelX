"""Tests for Futuris Context Exchange, Research-Informed Forecasting, and Combined Intelligence Reports."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.core.auth import seed_api_keys_from_settings
from intelx.core.enums import (
    ClaimOrigin,
    ClaimStatus,
    ClaimType,
    RunOutcome,
    RunStatus,
    SourceKind,
    TrustTier,
)
from intelx.core.settings import get_settings
from intelx.db.models import Finding
from intelx.db.repos import ClaimRepo, RunRepo, SourceRepo
from intelx.db.session import get_sessionmaker
from intelx.integrations.futuris_context import (
    FuturisContextProvider,
    ResearchTriggeredForecasting,
    generate_combined_intelligence_report,
)


@pytest.mark.asyncio
async def test_relevance_computation_and_signal_extraction():
    """Verify keyword overlap relevance scoring and directional signal extraction."""
    # 1. Relevance Scoring
    target_tokens = {"sodium", "ion", "battery", "energy", "density"}
    high_rel = FuturisContextProvider.compute_relevance(
        target_tokens,
        "Layered oxide sodium-ion cathode active energy density reached 160 Wh/kg",
    )
    assert high_rel >= 0.70

    low_rel = FuturisContextProvider.compute_relevance(
        target_tokens,
        "Superconducting quantum annealer demonstrated speedup on graph partitioning",
    )
    assert low_rel <= 0.35
    assert FuturisContextProvider.compute_relevance(set(), "unrelated input") == 0.0


def test_futuris_exogenous_signals_exclude_disputed_and_low_confidence_claims():
    active = SimpleNamespace(
        id="active-claim-001",
        text="Battery efficiency increased by 20 percent.",
        subject="Battery",
        predicate="efficiency increased",
        confidence=0.92,
        status=ClaimStatus.ACTIVE,
    )
    disputed = SimpleNamespace(
        id="disputed-claim-02",
        text="Battery output surged by 40 percent.",
        subject="Battery",
        predicate="output surged",
        confidence=0.98,
        status=ClaimStatus.DISPUTED,
    )
    low_confidence = SimpleNamespace(
        id="low-confidence-03",
        text="Battery output increased by 15 percent.",
        subject="Battery",
        predicate="output increased",
        confidence=0.42,
        status=ClaimStatus.ACTIVE,
    )

    signals = FuturisContextProvider._extract_signals([active, disputed, low_confidence])

    assert len(signals) == 1
    assert signals[0].direction == "positive"
    assert signals[0].source == "Claim active-c"


@pytest.mark.asyncio
async def test_futuris_context_provider_database_query():
    """Verify get_research_context populates findings, credibility, temporal, and exogenous features."""
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        # Create research run with verified claims and sources
        run = await RunRepo.create_run(
            session=session,
            objective="Evaluate solid state composite sulfide battery energy density and stability",
        )
        run.status = RunStatus.COMPLETED
        run.outcome = RunOutcome.ANSWERED
        run.completed_at = datetime.now(UTC)

        failed_run = await RunRepo.create_run(
            session=session,
            objective="Failed sodium battery run with unverified energy claims",
        )
        failed_run.status = RunStatus.FAILED
        failed_run.outcome = RunOutcome.FAILED
        failed_run.completed_at = datetime.now(UTC)
        session.add(
            Finding(
                run_id=failed_run.id,
                conclusion="FAILED_ONLY sodium battery evidence claimed 99% retention.",
                confidence=0.99,
            )
        )

        src = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.FILE,
            location="https://prl-physics.org/battery-study-2026",
            domain="prl-physics.org",
            publisher="Physical Review Letters",
            title="Physical Limitations and Energy Density of Composite Sulfide Anodes",
            trust_tier=TrustTier.TRUSTED,
            created_by_run_id=run.id,
        )
        doc_text = "The composite sulfide electrolyte demonstrated an energy density increase of 18% with 92% retention."
        doc = await SourceRepo.create_document(
            session=session,
            source_id=src.id,
            text_content=doc_text,
        )
        chunk = await SourceRepo.create_chunk(
            session=session,
            document_id=doc.id,
            idx=0,
            start_char=0,
            end_char=len(doc_text),
            text_content=doc_text,
        )
        quote_text = "energy density increase of 18%"
        span_s = doc_text.find(quote_text)
        span_e = span_s + len(quote_text)
        await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=src.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            text_content="Electrolyte demonstrated an energy density increase of 18%",
            subject="Composite Sulfide Electrolyte",
            predicate="energy density increase",
            object_val="18%",
            claim_type=ClaimType.MEASUREMENT,
            quote=quote_text,
            span_start=span_s,
            span_end=span_e,
            confidence=0.92,
            origin=ClaimOrigin.EXTRACTED,
            status=ClaimStatus.ACTIVE,
            created_by_agent="ExtractorAgent",
        )
        await session.commit()

        # Query Futuris research context
        response = await FuturisContextProvider.get_research_context(
            session=session,
            forecast_target="Solid state battery energy density growth",
            horizon="1y",
            lookback_days=7,
            domain="technical",
        )

        assert response.forecast_target == "Solid state battery energy density growth"
        assert response.horizon == "1y"
        assert len(response.research_findings) > 0
        assert all("FAILED_ONLY" not in finding.finding for finding in response.research_findings)
        assert len(response.exogenous_signals) > 0

        sig = response.exogenous_signals[0]
        assert sig.direction == "positive"
        assert sig.confidence >= 0.80

        # Credibility and temporal context
        assert response.source_credibility_summary.authoritative_sources_count >= 1
        assert len(response.temporal_context.recent_events) > 0


@pytest.mark.asyncio
async def test_futuris_context_excludes_failed_runs_instead_of_reusing_them():
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        failed_run = await RunRepo.create_run(
            session=session,
            objective="Sodium battery energy density study that failed verification",
        )
        failed_run.status = RunStatus.FAILED
        failed_run.outcome = RunOutcome.FAILED
        failed_run.completed_at = datetime.now(UTC)
        await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://unverified.example.test/sodium-study",
            title="Unverified sodium battery study",
            trust_tier=TrustTier.TRUSTED,
            created_by_run_id=failed_run.id,
        )
        session.add(
            Finding(
                run_id=failed_run.id,
                conclusion="Sodium battery energy density increased by 99 percent.",
                confidence=0.99,
            )
        )
        await session.commit()

        response = await FuturisContextProvider.get_research_context(
            session=session,
            forecast_target="Sodium battery energy density",
            horizon="6m",
            lookback_days=7,
            domain="technical",
        )

    assert response.research_findings == []
    assert response.source_credibility_summary.top_sources == []
    assert response.temporal_context.recent_events == []
    assert response.exogenous_signals == []


@pytest.mark.asyncio
async def test_research_triggered_forecasting_detect_and_notify():
    """Verify catalyst detection across market, regulatory, and threat domains and mock webhook dispatch."""
    # 1. Catalyst classification
    is_sig_mkt, cat_mkt, _ = ResearchTriggeredForecasting.detect_significant_trigger(
        "Commercial breakthrough in sodium-ion energy density achieved cost parity with LFP"
    )
    assert is_sig_mkt is True
    assert cat_mkt == "market_moving"

    is_sig_reg, cat_reg, _ = ResearchTriggeredForecasting.detect_significant_trigger(
        "SEC filing mandate requires strict compliance on supply chain emissions"
    )
    assert is_sig_reg is True
    assert cat_reg == "regulatory_change"

    is_sig_threat, cat_threat, _ = ResearchTriggeredForecasting.detect_significant_trigger(
        "Critical zero-day vulnerability CVE-2026-8888 discovered in energy grid firmware"
    )
    assert is_sig_threat is True
    assert cat_threat == "emerging_threat"

    is_routine, _, _ = ResearchTriggeredForecasting.detect_significant_trigger(
        "Standard laboratory calibration routine completed under ambient temperatures"
    )
    assert is_routine is False

    # 2. Webhook notification (mock mode)
    notify_res = await ResearchTriggeredForecasting.notify_futuris_research_relevant(
        finding_text="Commercial breakthrough in sodium-ion energy density achieved cost parity with LFP",
        run_id="run-test-12345",
        domain="market",
        confidence=0.90,
    )
    assert notify_res["status"] in ("delivered_mock", "delivered")
    assert notify_res["category"] == "market_moving"
    assert "payload" in notify_res


@pytest.mark.asyncio
async def test_futuris_context_api_endpoints():
    """Verify POST /api/v1/futuris/context and POST /api/v1/futuris/trigger-forecast."""
    settings = get_settings()
    settings.MOCK_MODE = True
    settings.FUTURIS_API_KEY = "futuris-secret-test-key"
    async with get_sessionmaker()() as session:
        await seed_api_keys_from_settings(session, settings)

    app = create_app()
    transport = ASGITransport(app=app)
    headers = {"X-API-Key": "futuris-secret-test-key"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. POST /api/v1/futuris/context
        ctx_resp = await client.post(
            "/api/v1/futuris/context",
            json={
                "forecast_target": "Sodium-ion battery adoption curve 2027",
                "horizon": "12m",
                "requesting_context": {
                    "domain": "market",
                    "lookback_days": 14,
                },
            },
            headers=headers,
        )
        assert ctx_resp.status_code == 200
        ctx_data = ctx_resp.json()
        assert ctx_data["forecast_target"] == "Sodium-ion battery adoption curve 2027"
        assert ctx_data["horizon"] == "12m"
        assert "research_findings" in ctx_data
        assert "source_credibility_summary" in ctx_data
        assert "temporal_context" in ctx_data
        assert "exogenous_signals" in ctx_data

        # 2. POST /api/v1/futuris/trigger-forecast
        trig_resp = await client.post(
            "/api/v1/futuris/trigger-forecast",
            json={
                "finding_text": "Zero-day exploit detected in battery management system firmware",
                "run_id": "run-sec-999",
                "domain": "security",
                "confidence": 0.95,
            },
            headers=headers,
        )
        assert trig_resp.status_code == 200
        trig_data = trig_resp.json()
        assert trig_data["category"] == "emerging_threat"
        assert trig_data["status"] in ("delivered_mock", "delivered")


@pytest.mark.asyncio
async def test_combined_intelligence_report_generation():
    """Verify synthesis of IntelX research explanations with Futuris calibrated forecasts."""
    research_input = {
        "objective": "Sodium-Ion Cathode Market Parity",
        "overall_confidence": "High",
        "findings": [
            {
                "statement": "Optimized layered oxide formulation achieved 160 Wh/kg energy density at 1C discharge.",
                "confidence_score": 0.92,
                "citations": [
                    {
                        "source_title": "Advanced Energy Materials Study",
                        "source_url": "https://aem-journal.org/sodium-ion-2026",
                        "verbatim_span": "achieved 160 Wh/kg energy density at 1C discharge",
                    }
                ],
            }
        ],
    }

    forecast_input = {
        "target": "Sodium-Ion Cathode Market Parity",
        "horizon": "2027",
        "predictions": [
            {
                "statement": "Commercial parity with low-cost LFP packs is projected by Q3 2027.",
                "probability": "84%",
            }
        ],
    }

    # Generate Combined Product
    report = generate_combined_intelligence_report(research_input, forecast_input)

    assert report.topic == "Sodium-Ion Cathode Market Parity"
    assert "The 'Why'" in report.combined_markdown
    assert "The 'What Next'" in report.combined_markdown
    assert "160 Wh/kg" in report.combined_markdown
    assert "Q3 2027" in report.combined_markdown
    assert len(report.citations) >= 1
    assert "Advanced Energy Materials Study" in report.citations[0].source_title

    # Test via API endpoint
    settings = get_settings()
    settings.MOCK_MODE = True
    settings.FUTURIS_API_KEY = "futuris-report-test-key"
    async with get_sessionmaker()() as session:
        await seed_api_keys_from_settings(session, settings)
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/futuris/combined-report",
            headers={"X-API-Key": "futuris-report-test-key"},
            json={
                "research_data": research_input,
                "forecast_data": forecast_input,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "Sodium-Ion Cathode Market Parity"
        assert "combined_markdown" in data
        assert "synthesis_why_and_what_next" in data
