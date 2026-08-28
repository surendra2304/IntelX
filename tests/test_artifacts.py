"""Tests for INTELX Synthesis, Report Rendering, Citation Integrity, and Artifact Generation."""

from pathlib import Path

import pytest
from sqlalchemy import select

from intelx.agents.extractor import (
    ExtractedClaim,
    ExtractedEntity,
    ExtractionResult,
    ExtractorAgent,
    RelativeSpan,
)
from intelx.agents.scout import ScoutAgent, ScoutOutput, SourceCandidate
from intelx.core.enums import (
    ArtifactFormat,
    ArtifactType,
    ClaimStatus,
    ClaimType,
)
from intelx.core.errors import IntegrityError
from intelx.core.report import (
    filter_and_ground_findings,
    render_report_markdown,
    validate_citations,
)
from intelx.db.models import Artifact
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker
from intelx.memory.artifacts import ReportArtifact
from intelx.models.gateway import ModelGateway, Usage
from intelx.orchestration.engine import OrchestrationEngine
from intelx.orchestration.worker import OrchestrationWorker


@pytest.fixture
def db_session_factory():
    """Get active async sessionmaker."""
    return get_sessionmaker()


def test_citation_integrity_broken_token_raises():
    """Verify that unresolvable citation tokens raise IntegrityError."""
    valid_sources = {"src-12345678", "src-87654321"}
    valid_claims = {"clm-11111111", "clm-22222222"}

    valid_md = "According to [S:src-1234] and verified by [C:clm-1111]."
    validate_citations(valid_md, valid_sources, valid_claims)

    broken_src_md = "According to [S:nonexistent-src] data."
    with pytest.raises(IntegrityError):
        validate_citations(broken_src_md, valid_sources, valid_claims)

    broken_clm_md = "Verified assertion [C:ghost-claim]."
    with pytest.raises(IntegrityError):
        validate_citations(broken_clm_md, valid_sources, valid_claims)


def test_groundedness_disputed_claim_moved_to_unverified():
    """Verify finding supported only by DISPUTED claims is partitioned to unverified."""
    claims_by_id = {
        "claim-active": {"id": "claim-active", "status": ClaimStatus.ACTIVE},
        "claim-disputed": {"id": "claim-disputed", "status": ClaimStatus.DISPUTED},
    }

    findings = [
        {
            "statement": "Supported finding",
            "confidence": 0.85,
            "claim_ids": ["claim-active"],
        },
        {
            "statement": "Contested finding",
            "confidence": 0.70,
            "claim_ids": ["claim-disputed"],
        },
    ]

    grounded, unverified = filter_and_ground_findings(findings, claims_by_id)

    assert len(grounded) == 1
    assert grounded[0]["statement"] == "Supported finding"

    assert len(unverified) == 1
    assert unverified[0]["statement"] == "Contested finding"
    assert "unverified_reason" in unverified[0]


def test_contradicted_pair_rendered_in_contradictions_section():
    """Verify disputed claims appear in the Contradictions section with citations."""
    claims = [
        {
            "id": "c-alpha-12345",
            "text": "Energy density is 450 Wh/kg",
            "status": ClaimStatus.DISPUTED,
            "source_id": "s-alpha-99999",
        }
    ]
    sources = [
        {
            "id": "s-alpha-99999",
            "title": "Lab Alpha Battery Study",
            "domain": "lab-alpha.org",
            "trust_tier": "STANDARD",
        }
    ]

    md = render_report_markdown(
        objective="Assess solid-state battery energy density",
        executive_answer="Contested values exist across independent laboratories.",
        grounded_findings=[],
        unverified_findings=[],
        claims=claims,
        sources=sources,
    )

    assert "## Contradictions & Disagreements" in md
    assert "Energy density is 450 Wh/kg" in md
    assert "[C:c-alpha-]" in md
    assert "[S:s-alpha-]" in md


def test_report_json_schema_validation(tmp_path):
    """Verify report.json validates against the ReportArtifact pydantic schema."""
    report_dict = {
        "schema_version": "v1.0",
        "meta": {
            "run_id": "run-test-123",
            "objective": "Test schema validation",
            "status": "COMPLETED",
            "outcome": "ANSWERED",
            "started_at": "2026-08-28T12:00:00Z",
            "completed_at": "2026-08-28T12:05:00Z",
            "input_tokens": 1200,
            "output_tokens": 400,
            "usd_cost": 0.05,
            "tool_calls": 3,
        },
        "executive_answer": "Valid executive report answer.",
        "overall_confidence_label": "High",
        "key_findings": [
            {
                "statement": "Validated scalable throughput.",
                "confidence": 0.90,
                "confidence_label": "High",
                "claim_ids": ["c1"],
            }
        ],
        "unverified_findings": [],
        "claims_referenced": [],
        "contradictions": [],
        "gaps": ["Independent benchmarking limited."],
        "sources": [],
        "degradations": [],
    }

    artifact = ReportArtifact.model_validate(report_dict)
    assert artifact.schema_version == "v1.0"
    assert artifact.meta.run_id == "run-test-123"
    assert len(artifact.key_findings) == 1


@pytest.mark.asyncio
async def test_full_mock_mode_end_to_end_artifacts_and_headings(db_session_factory, tmp_path):
    """Verify full end-to-end run produces all 4 artifacts with all 9 required section headings."""
    async with db_session_factory() as session:
        fixture_path = Path("./tests/fixtures/docs/quantum_report.md").resolve()
        run = await RunRepo.create_run(
            session,
            objective="Assess quantum error correction progress",
            scope_json={"domain_hints": [str(fixture_path)]},
        )
        await session.commit()

        class FixtureScoutAgent(ScoutAgent):
            async def execute(self, subquestion, **kwargs):
                return ScoutOutput(
                    candidates=[
                        SourceCandidate(
                            location=str(fixture_path),
                            title="Quantum Progress Report",
                            reason="Fixture ground truth",
                            expected_relevance=1.0,
                        )
                    ]
                )

        class AccurateExtractor(ExtractorAgent):
            def __init__(self):
                super().__init__()

                class AccurateGateway(ModelGateway):
                    async def complete(
                        self, messages, role="extractor", schema_model=None, **kwargs
                    ):
                        if role == "extractor":
                            ext = ExtractionResult(
                                claims=[
                                    ExtractedClaim(
                                        text=(
                                            "Joint fabrication efforts demonstrated a 40 percent "
                                            "reduction in crosstalk noise."
                                        ),
                                        quote="reduction in crosstalk noise",
                                        relative_span=RelativeSpan(start=0, end=27),
                                        claim_type=ClaimType.FACT,
                                    )
                                ],
                                entities=[ExtractedEntity(name="TSMC", type="ORG")],
                                events=[],
                            )
                            return type(
                                "Res",
                                (),
                                {
                                    "parsed": ext,
                                    "text": ext.model_dump_json(),
                                    "usage": Usage(),
                                    "provider": "mock",
                                    "model": "mock",
                                },
                            )()
                        return await super().complete(
                            messages=messages, role=role, schema_model=schema_model, **kwargs
                        )

                self.gateway = AccurateGateway()

        engine = OrchestrationEngine(
            scout_agent=FixtureScoutAgent(), extractor_agent=AccurateExtractor()
        )
        worker = OrchestrationWorker(engine=engine)

        processed = await worker.run_once(db_session_factory)
        assert processed is True

        # Verify artifacts in database
        async with db_session_factory() as verify_session:
            stmt_art = select(Artifact).where(Artifact.run_id == run.id)
            artifacts = list((await verify_session.execute(stmt_art)).scalars().all())
            assert len(artifacts) == 4

            art_types = {a.type for a in artifacts}
            assert ArtifactType.REPORT in art_types
            assert ArtifactType.EVIDENCE_PACK in art_types
            assert ArtifactType.SOURCE_LIST in art_types

            # Verify files exist on disk
            report_md_art = next(a for a in artifacts if a.format == ArtifactFormat.MD)
            md_path = Path(report_md_art.path)
            assert md_path.exists()
            content = md_path.read_text(encoding="utf-8")

            # Check all 9 required section headings
            assert "# Research Report:" in content
            assert "## Direct Answer" in content
            assert "## Key Findings" in content
            assert "## Evidence Map" in content
            assert "## Contradictions & Disagreements" in content
            assert "## What We Could Not Establish" in content
            assert "## Limitations & Criticisms" in content
            assert "## Degradations" in content
            assert "## Methodology Note" in content
            assert "## Sources" in content
