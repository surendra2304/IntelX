"""Tests for INTELX Trust Layer: Independence, Confidence, Verifier, Analyst, Critic, and Entity."""

import pytest
from sqlalchemy import select

from intelx.agents.analyst import AnalystAgent
from intelx.agents.critic import CriticAgent
from intelx.agents.retriever import RetrievedDoc, RetrieverAgent, RetrieverOutput
from intelx.agents.verifier import VerificationVerdict, VerifierAgent
from intelx.core.confidence import compute_confidence_score
from intelx.core.enums import (
    ClaimOrigin,
    ClaimStatus,
    ClaimType,
    EntityMergeStatus,
    EntityType,
    EvidenceSupportType,
    SourceKind,
    TrustTier,
)
from intelx.core.independence import compute_3gram_jaccard, is_independent_evidence
from intelx.db.models import EntityMerge, Event, Evidence
from intelx.db.repos import ClaimRepo, RunRepo
from intelx.db.session import get_sessionmaker
from intelx.memory.entities import EntityResolver
from intelx.memory.normalize import ingest_and_normalize
from intelx.models.gateway import ModelGateway
from intelx.models.types import Usage


@pytest.fixture
def db_session_factory():
    """Get active async sessionmaker."""
    return get_sessionmaker()


def test_independence_rules():
    """Verify evidence independence detection across publishers, domains, and n-gram overlap."""
    source_a = {
        "domain": "reuters.com",
        "publisher": "Reuters News",
        "fingerprint": "fp_reuters_101",
    }
    source_b_same_pub = {
        "domain": "yahoo.com",
        "publisher": "Reuters News",
        "fingerprint": "fp_yahoo_102",
    }
    source_c_syndicated = {
        "domain": "techwire.net",
        "publisher": "TechWire",
        "fingerprint": "fp_techwire_103",
    }
    source_d_independent = {
        "domain": "nature.com",
        "publisher": "Nature Publishing Group",
        "fingerprint": "fp_nature_104",
    }

    quote_orig = "TSMC and IBM demonstrated 40 percent reduction in crosstalk noise."
    quote_near_copy = (
        "TSMC and IBM demonstrated 40 percent reduction in crosstalk noise across transmon qubits."
    )
    quote_diff = "Independent empirical evaluation of fault tolerance in superconducting circuits."

    # 1. Same publisher -> Dependent
    is_indep_pub, _ = is_independent_evidence(
        source_a, None, quote_orig, source_b_same_pub, None, quote_diff
    )
    assert is_indep_pub is False

    # 2. Syndicated near-copy (Jaccard >= 0.50) -> Dependent
    jaccard = compute_3gram_jaccard(quote_orig, quote_near_copy)
    assert jaccard >= 0.50
    is_indep_syn, _ = is_independent_evidence(
        source_a, None, quote_orig, source_c_syndicated, None, quote_near_copy
    )
    assert is_indep_syn is False

    # 3. Genuinely different -> Independent
    is_indep_true, _ = is_independent_evidence(
        source_a, None, quote_orig, source_d_independent, None, quote_diff
    )
    assert is_indep_true is True


def test_confidence_formula_properties():
    """Verify deterministic property rules of the v1-composite confidence formula."""
    # 1. Base tier checks
    score_trusted, _, _ = compute_confidence_score(TrustTier.TRUSTED)
    assert score_trusted == 0.70

    score_standard, _, _ = compute_confidence_score(TrustTier.STANDARD)
    assert score_standard == 0.50

    score_quarantine, _, _ = compute_confidence_score(TrustTier.QUARANTINE)
    assert score_quarantine == 0.20

    # 2. Corroboration bonus capped at 3 (+0.45 max)
    score_corrob_3, _, _ = compute_confidence_score(
        TrustTier.STANDARD, independent_corroborations=3
    )
    assert score_corrob_3 == 0.95

    score_corrob_5, _, _ = compute_confidence_score(
        TrustTier.STANDARD, independent_corroborations=5
    )
    assert score_corrob_5 == 0.95

    # 3. Penalties: Opinion (-0.25) and Staleness (-0.20)
    score_opinion, _, _ = compute_confidence_score(
        TrustTier.STANDARD, claim_type=ClaimType.STATEMENT_OF_OPINION
    )
    assert score_opinion == 0.25

    score_stale, _, _ = compute_confidence_score(TrustTier.STANDARD, is_stale=True)
    assert score_stale == 0.30

    # 4. LLM adjustment clamping ([-0.10, +0.10])
    score_adj_high, _, _ = compute_confidence_score(TrustTier.STANDARD, llm_adjustment=0.50)
    assert score_adj_high == 0.60

    # 5. Clamping bounds [0.05, 0.95]
    score_min, _, _ = compute_confidence_score(
        TrustTier.QUARANTINE, is_stale=True, claim_type=ClaimType.FORECAST, llm_adjustment=-0.10
    )
    assert score_min == 0.05


@pytest.mark.asyncio
async def test_contradiction_handling_and_disputed_status(db_session_factory):
    """Verify contradicting evidence marks both claims DISPUTED and records two-sided evidence."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session, objective="Battery lifecycle contradiction test")

        text_1 = "Lab testing verified that degradation was strictly under 5 percent."
        s1, doc1, chunks1, _ = await ingest_and_normalize(
            session=session,
            raw_bytes=text_1.encode("utf-8"),
            location="https://lab1.org/paper.html",
            kind=SourceKind.WEB,
            domain="lab1.org",
            title="Lab 1 Report",
        )

        quote_1 = "strictly under 5 percent"
        s1_start = text_1.index(quote_1)
        claim1 = await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=s1.id,
            document_id=doc1.id,
            chunk_id=chunks1[0].id,
            text_content="Cell degradation was under 5 percent.",
            quote=quote_1,
            span_start=s1_start,
            span_end=s1_start + len(quote_1),
            claim_type=ClaimType.MEASUREMENT,
            origin=ClaimOrigin.EXTRACTED,
            status=ClaimStatus.ACTIVE,
        )

        text_2 = "Audit results showed cell capacity degradation exceeded 25 percent under load."
        s2, doc2, chunks2, _ = await ingest_and_normalize(
            session=session,
            raw_bytes=text_2.encode("utf-8"),
            location="https://independent-audit.org/critique.html",
            kind=SourceKind.WEB,
            domain="independent-audit.org",
            title="Independent Audit",
        )

        quote_2 = "exceeded 25 percent"
        s2_start = text_2.index(quote_2)
        await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=s2.id,
            document_id=doc2.id,
            chunk_id=chunks2[0].id,
            text_content="Degradation exceeded 25 percent.",
            quote=quote_2,
            span_start=s2_start,
            span_end=s2_start + len(quote_2),
            claim_type=ClaimType.MEASUREMENT,
            origin=ClaimOrigin.EXTRACTED,
            status=ClaimStatus.ACTIVE,
        )

        # Mock Verifier Gateway returning contradiction verdict
        class ContradictingVerifierGateway(ModelGateway):
            async def complete(self, messages, **kwargs):
                role = kwargs.get("role", "")
                if role == "scout":
                    from intelx.agents.scout import ScoutOutput, SourceCandidate

                    return type(
                        "Res",
                        (),
                        {
                            "parsed": ScoutOutput(
                                candidates=[
                                    SourceCandidate(
                                        location="https://independent-audit.org/critique.html",
                                        title="Independent Audit",
                                        reason="Audit finding",
                                    )
                                ]
                            )
                        },
                    )()
                elif role == "extractor":
                    from intelx.agents.extractor import (
                        ExtractedClaim,
                        ExtractionResult,
                        RelativeSpan,
                    )

                    return type(
                        "Res",
                        (),
                        {
                            "parsed": ExtractionResult(
                                claims=[
                                    ExtractedClaim(
                                        text="Degradation exceeded 25 percent under load.",
                                        quote=quote_2,
                                        relative_span=RelativeSpan(start=0, end=len(quote_2)),
                                        claim_type=ClaimType.MEASUREMENT,
                                    )
                                ]
                            )
                        },
                    )()
                elif role == "verifier":
                    return type(
                        "Res",
                        (),
                        {
                            "parsed": VerificationVerdict(
                                verdict="CONTRADICTED",
                                support_type=EvidenceSupportType.CONTRADICTS,
                                reasoning="Audit reports 25% degradation vs 5% claimed.",
                                contradiction_details="5% vs 25% degradation rate",
                            ),
                            "text": "CONTRADICTED",
                            "usage": Usage(),
                        },
                    )()
                return await super().complete(messages, **kwargs)

        class MockRetriever(RetrieverAgent):
            async def execute(self, candidates, session, run_id=None, **kwargs):
                return RetrieverOutput(
                    retrieved=[
                        RetrievedDoc(
                            source_id=s2.id,
                            document_id=doc2.id,
                            location=s2.location,
                            chunks_count=len(chunks2),
                        )
                    ]
                )

        verifier = VerifierAgent(
            gateway=ContradictingVerifierGateway(),
            retriever_agent=MockRetriever(),
        )
        await verifier.execute(
            claims=[claim1],
            session=session,
            run_id=run.id,
        )

        assert claim1.status == ClaimStatus.DISPUTED

        stmt_ev = select(Event).where(Event.run_id == run.id, Event.type == "claim.disputed")
        disputed_ev = (await session.execute(stmt_ev)).scalar_one_or_none()
        assert disputed_ev is not None

        stmt_evi = select(Evidence).where(
            Evidence.claim_id == claim1.id,
            Evidence.support_type == EvidenceSupportType.CONTRADICTS,
        )
        contra_evi = (await session.execute(stmt_evi)).scalars().all()
        assert len(contra_evi) >= 1


@pytest.mark.asyncio
async def test_entity_resolution_workflow(db_session_factory):
    """Verify EntityResolver auto-merges high similarity and proposes near-matches."""
    async with db_session_factory() as session:
        run = await RunRepo.create_run(session, objective="Entity resolution test")

        # 1. Create canonical entity
        ent1, _ = await EntityResolver.resolve_or_create(
            session=session,
            name="Taiwan Semiconductor Manufacturing Company",
            entity_type=EntityType.ORG,
            aliases=["TSMC"],
            run_id=run.id,
        )
        assert ent1.id is not None

        # 2. Match via alias -> returns existing canonical entity
        ent_alias, status_alias = await EntityResolver.resolve_or_create(
            session=session,
            name="TSMC",
            entity_type=EntityType.ORG,
            run_id=run.id,
        )
        assert ent_alias.id == ent1.id
        assert status_alias == EntityMergeStatus.APPLIED

        # 3. Near-match with suffix variance (score >= 0.95) -> Auto-applies merge
        ent_auto, status_auto = await EntityResolver.resolve_or_create(
            session=session,
            name="Taiwan Semiconductor Manufacturing Co",
            entity_type=EntityType.ORG,
            run_id=run.id,
        )
        assert ent_auto.id == ent1.id
        assert status_auto == EntityMergeStatus.APPLIED

        # 4. Moderate similarity (0.70 <= score < 0.95) -> Creates PROPOSED merge
        ent_prop, status_prop = await EntityResolver.resolve_or_create(
            session=session,
            name="Taiwan Semiconductor Manufacturing Enterprise",
            entity_type=EntityType.ORG,
            run_id=run.id,
        )
        assert ent_prop.id != ent1.id
        assert status_prop == EntityMergeStatus.PROPOSED

        # Check entity_merges table
        stmt_merges = select(EntityMerge)
        merges = (await session.execute(stmt_merges)).scalars().all()
        assert len(merges) >= 2
        statuses = [m.status for m in merges]
        assert EntityMergeStatus.APPLIED in statuses
        assert EntityMergeStatus.PROPOSED in statuses


@pytest.mark.asyncio
async def test_critic_and_analyst_agents():
    """Verify AnalystAgent and CriticAgent produce valid structured outputs."""
    # 1. Analyst Agent
    analyst = AnalystAgent()
    mock_claims = [
        {"id": "c1", "text": "TSMC 2nm node achieved 80% yield.", "confidence": 0.90},
        {"id": "c2", "text": "Samsung 2nm pilot fab started in Q1 2026.", "confidence": 0.85},
    ]
    analysis = await analyst.execute(claims=mock_claims)
    assert hasattr(analysis, "timeline")
    assert hasattr(analysis, "themes")

    # 2. Critic Agent
    critic = CriticAgent()
    critique = await critic.execute(
        draft_findings=["2nm foundries will dominate 70% of shipments by year end."],
        claims=mock_claims,
    )
    assert critique.severity in ("LOW", "MEDIUM", "HIGH")
    assert hasattr(critique, "unsupported_conclusions")
