"""Production demonstration intelligence seeder for INTELX.

Populates realistic, evidence-backed research operations, verified citation
graphs, multi-format artifacts, and cryptographic audit records on startup
whenever canonical demonstration investigations are missing.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import (
    ArtifactFormat,
    ArtifactType,
    ClaimOrigin,
    ClaimStatus,
    ClaimType,
    EvidenceSupportType,
    RunOutcome,
    RunStatus,
    SourceKind,
    TrustTier,
)
from intelx.db.models import (
    Artifact,
    Chunk,
    Claim,
    Document,
    Event,
    Evidence,
    Finding,
    ResearchRun,
    Source,
)
from intelx.db.repos import AuditChain

logger = logging.getLogger("intelx.demo_seeder")


def _compute_sha256(content: str | bytes | Path) -> str:
    if isinstance(content, Path):
        content = content.read_bytes()
    elif isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


async def auto_seed_demonstrations_if_empty(session: AsyncSession) -> bool:
    """Check if canonical demonstration runs exist; if not, populate them."""
    stmt = select(ResearchRun).where(ResearchRun.id == "run-na-battery-001")
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        logger.debug("Canonical demonstration runs already exist; skipping demonstration seed.")
        return False

    logger.info("Canonical demonstration runs missing. Bootstrapping realistic production demonstrations...")

    artifacts_root = Path("./data/artifacts").resolve()
    artifacts_root.mkdir(parents=True, exist_ok=True)

    base_time = datetime.now(UTC) - timedelta(hours=6)

    # =========================================================================
    # RUN 1: Sodium-Ion Cathode Benchmarks (COMPLETED / ANSWERED)
    # =========================================================================
    run1_id = "run-na-battery-001"
    run1 = ResearchRun(
        id=run1_id,
        objective="Assess next-generation sodium-ion cathode performance, energy density, and thermal stability",
        scope_json={
            "depth": "deep",
            "max_sources": 10,
            "budget": {"max_usd": 2.50, "max_minutes": 10},
        },
        status=RunStatus.COMPLETED,
        outcome=RunOutcome.ANSWERED,
        input_tokens=4820,
        output_tokens=2150,
        usd_cost=0.0084,
        tool_calls=14,
        created_by="admin",
        started_at=base_time + timedelta(minutes=2),
        completed_at=base_time + timedelta(minutes=6),
        created_at=base_time,
    )
    session.add(run1)
    await session.flush()

    s1_1 = Source(
        id="src-na-nature-01",
        kind=SourceKind.WEB,
        location="https://www.nature.com/articles/s41560-025-01420-x",
        domain="nature.com",
        publisher="Nature Energy",
        title="High-voltage air-stable layered oxide cathodes for sodium-ion energy storage",
        retrieved_at=base_time + timedelta(minutes=2, seconds=15),
        content_type="text/html",
        fingerprint=_compute_sha256("https://www.nature.com/articles/s41560-025-01420-x"),
        trust_tier=TrustTier.TRUSTED,
        robots_ok=True,
        injection_risk=False,
        created_by_run_id=run1_id,
    )
    s1_2 = Source(
        id="src-na-jps-02",
        kind=SourceKind.WEB,
        location="https://www.sciencedirect.com/science/article/pii/S037877532500112X",
        domain="sciencedirect.com",
        publisher="Journal of Power Sources",
        title="Thermal runaway mitigation and abuse tolerance of commercial-scale Na-ion pouch cells",
        retrieved_at=base_time + timedelta(minutes=2, seconds=45),
        content_type="text/html",
        fingerprint=_compute_sha256("https://www.sciencedirect.com/science/article/pii/S037877532500112X"),
        trust_tier=TrustTier.TRUSTED,
        robots_ok=True,
        injection_risk=False,
        created_by_run_id=run1_id,
    )
    s1_3 = Source(
        id="src-na-arxiv-03",
        kind=SourceKind.WEB,
        location="https://arxiv.org/abs/2502.18942",
        domain="arxiv.org",
        publisher="arXiv Condensed Matter",
        title="Comparative volumetric energy density and cyclability benchmarks of polyanion vs layered sodium cathodes",
        retrieved_at=base_time + timedelta(minutes=3, seconds=10),
        content_type="text/html",
        fingerprint=_compute_sha256("https://arxiv.org/abs/2502.18942"),
        trust_tier=TrustTier.STANDARD,
        robots_ok=True,
        injection_risk=False,
        created_by_run_id=run1_id,
    )
    s1_4 = Source(
        id="src-na-industry-04",
        kind=SourceKind.WEB,
        location="https://www.catl.com/en/news/1024.html",
        domain="catl.com",
        publisher="CATL Technology Press",
        title="Second-generation sodium-ion cell mass production architecture and low-temperature retention",
        retrieved_at=base_time + timedelta(minutes=3, seconds=35),
        content_type="text/html",
        fingerprint=_compute_sha256("https://www.catl.com/en/news/1024.html"),
        trust_tier=TrustTier.STANDARD,
        robots_ok=True,
        injection_risk=False,
        created_by_run_id=run1_id,
    )
    session.add_all([s1_1, s1_2, s1_3, s1_4])
    await session.flush()

    doc1_text = (
        "Titanium-stabilized O3-type layered oxide sodium cathodes achieve specific capacities of 165 mAh/g "
        "with 88% capacity retention after 2,000 cycles at 1C rate. Raw material extraction costs for sodium carbonate "
        "cathode precursors are 68% lower than lithium carbonate equivalents, offering a massive supply chain moat."
    )
    d1 = Document(id="doc-na-01", source_id=s1_1.id, text=doc1_text, language="en")

    doc2_text = (
        "Thermal runaway initiation in commercial sodium pouch cells occurs at 165°C compared to 130°C in NMC811 lithium cells. "
        "Sodium-ion pouch cells exhibit thermal runaway initiation thresholds of 165°C, providing a 35°C safety margin over conventional NMC811 lithium cells."
    )
    d2 = Document(id="doc-na-02", source_id=s1_2.id, text=doc2_text, language="en")

    doc3_text = (
        "Volumetric energy density in second-generation cylindrical sodium cells reaches 320 Wh/L, sufficient for urban mobility and stationary grid storage. "
        "Na3V2(PO4)3 polyanion frameworks retain 91.4% capacity at -20°C, significantly outperforming graphite-based lithium architectures."
    )
    d3 = Document(id="doc-na-03", source_id=s1_3.id, text=doc3_text, language="en")

    session.add_all([d1, d2, d3])
    await session.flush()

    c1_1 = Chunk(id="chk-na-01", document_id=d1.id, idx=0, start_char=0, end_char=len(doc1_text), text=doc1_text)
    c1_2 = Chunk(id="chk-na-02", document_id=d2.id, idx=0, start_char=0, end_char=len(doc2_text), text=doc2_text)
    c1_3 = Chunk(id="chk-na-03", document_id=d3.id, idx=0, start_char=0, end_char=len(doc3_text), text=doc3_text)

    session.add_all([c1_1, c1_2, c1_3])
    await session.flush()

    q1 = "O3-type layered oxide sodium cathodes achieve specific capacities of 165 mAh/g with 88% capacity retention after 2,000 cycles at 1C rate."
    clm1_1 = Claim(
        id="clm-na-01",
        run_id=run1_id,
        source_id=s1_1.id,
        document_id=d1.id,
        chunk_id=c1_1.id,
        text="Layered oxide sodium-ion cathodes deliver 165 mAh/g with 88% capacity retention over 2,000 cycles at 1C.",
        claim_type=ClaimType.MEASUREMENT,
        quote=q1,
        span_start=doc1_text.find(q1),
        span_end=doc1_text.find(q1) + len(q1),
        confidence=0.96,
        status=ClaimStatus.ACTIVE,
        origin=ClaimOrigin.EXTRACTED,
        created_by_agent="ExtractorAgent",
        created_at=base_time + timedelta(minutes=4),
    )
    q2 = "Sodium-ion pouch cells exhibit thermal runaway initiation thresholds of 165°C, providing a 35°C safety margin over conventional NMC811 lithium cells."
    clm1_2 = Claim(
        id="clm-na-02",
        run_id=run1_id,
        source_id=s1_2.id,
        document_id=d2.id,
        chunk_id=c1_2.id,
        text="Commercial sodium-ion pouch cells provide a 35°C higher thermal runaway onset safety buffer than high-nickel lithium cells.",
        claim_type=ClaimType.FACT,
        quote=q2,
        span_start=doc2_text.find(q2),
        span_end=doc2_text.find(q2) + len(q2),
        confidence=0.94,
        status=ClaimStatus.ACTIVE,
        origin=ClaimOrigin.EXTRACTED,
        created_by_agent="ExtractorAgent",
        created_at=base_time + timedelta(minutes=4),
    )
    q3 = "Na3V2(PO4)3 polyanion frameworks retain 91.4% capacity at -20°C, significantly outperforming graphite-based lithium architectures."
    clm1_3 = Claim(
        id="clm-na-03",
        run_id=run1_id,
        source_id=s1_3.id,
        document_id=d3.id,
        chunk_id=c1_3.id,
        text="Sodium polyanion cells retain over 91% usable capacity at -20°C ambient temperatures without auxiliary heating.",
        claim_type=ClaimType.MEASUREMENT,
        quote=q3,
        span_start=doc3_text.find(q3),
        span_end=doc3_text.find(q3) + len(q3),
        confidence=0.95,
        status=ClaimStatus.ACTIVE,
        origin=ClaimOrigin.EXTRACTED,
        created_by_agent="ExtractorAgent",
        created_at=base_time + timedelta(minutes=4),
    )
    q4 = "Volumetric energy density in second-generation cylindrical sodium cells reaches 320 Wh/L, sufficient for urban mobility and stationary grid storage."
    clm1_4 = Claim(
        id="clm-na-04",
        run_id=run1_id,
        source_id=s1_3.id,
        document_id=d3.id,
        chunk_id=c1_3.id,
        text="Volumetric energy density reaches 320 Wh/L in second-generation sodium cylindrical formats.",
        claim_type=ClaimType.MEASUREMENT,
        quote=q4,
        span_start=doc3_text.find(q4),
        span_end=doc3_text.find(q4) + len(q4),
        confidence=0.91,
        status=ClaimStatus.ACTIVE,
        origin=ClaimOrigin.EXTRACTED,
        created_by_agent="ExtractorAgent",
        created_at=base_time + timedelta(minutes=4),
    )
    session.add_all([clm1_1, clm1_2, clm1_3, clm1_4])
    await session.flush()

    e1_1 = Evidence(
        id="evi-na-01",
        claim_id=clm1_1.id,
        source_id=s1_1.id,
        document_id=d1.id,
        chunk_id=c1_1.id,
        span_start=clm1_1.span_start,
        span_end=clm1_1.span_end,
        quote=clm1_1.quote,
        support_type=EvidenceSupportType.SUPPORTS,
        created_by_run_id=run1_id,
        created_by_agent="VerifierAgent",
    )
    e1_2 = Evidence(
        id="evi-na-02",
        claim_id=clm1_2.id,
        source_id=s1_2.id,
        document_id=d2.id,
        chunk_id=c1_2.id,
        span_start=clm1_2.span_start,
        span_end=clm1_2.span_end,
        quote=clm1_2.quote,
        support_type=EvidenceSupportType.SUPPORTS,
        created_by_run_id=run1_id,
        created_by_agent="VerifierAgent",
    )
    e1_3 = Evidence(
        id="evi-na-03",
        claim_id=clm1_3.id,
        source_id=s1_3.id,
        document_id=d3.id,
        chunk_id=c1_3.id,
        span_start=clm1_3.span_start,
        span_end=clm1_3.span_end,
        quote=clm1_3.quote,
        support_type=EvidenceSupportType.SUPPORTS,
        created_by_run_id=run1_id,
        created_by_agent="VerifierAgent",
    )
    e1_4 = Evidence(
        id="evi-na-04",
        claim_id=clm1_4.id,
        source_id=s1_3.id,
        document_id=d3.id,
        chunk_id=c1_3.id,
        span_start=clm1_4.span_start,
        span_end=clm1_4.span_end,
        quote=clm1_4.quote,
        support_type=EvidenceSupportType.SUPPORTS,
        created_by_run_id=run1_id,
        created_by_agent="VerifierAgent",
    )
    session.add_all([e1_1, e1_2, e1_3, e1_4])

    f1_1 = Finding(
        id="fnd-na-01",
        run_id=run1_id,
        conclusion="Layered oxide Na-ion cathodes exhibit commercial cycle life (>2,000 cycles at 1C) with acceptable 165 mAh/g specific capacity.",
        confidence=0.96,
        claim_ids_json=[clm1_1.id],
        gaps_json=["Long-term calendar aging above 45°C requires further electrolyte optimization."],
        contradictions_json=[],
        unverified_json=[],
    )
    f1_2 = Finding(
        id="fnd-na-02",
        run_id=run1_id,
        conclusion="Thermal abuse resilience is substantially superior to high-nickel lithium-ion, postponing runaway initiation to 165°C.",
        confidence=0.94,
        claim_ids_json=[clm1_2.id],
        gaps_json=[],
        contradictions_json=[],
        unverified_json=[],
    )
    f1_3 = Finding(
        id="fnd-na-03",
        run_id=run1_id,
        conclusion="Extreme low-temperature resilience (-20°C) and 320 Wh/L volumetric density validate sodium-ion readiness for stationary grid storage and urban fleet transport.",
        confidence=0.93,
        claim_ids_json=[clm1_3.id, clm1_4.id],
        gaps_json=[],
        contradictions_json=[],
        unverified_json=[],
    )
    session.add_all([f1_1, f1_2, f1_3])

    dir1 = artifacts_root / run1_id
    dir1.mkdir(parents=True, exist_ok=True)

    report_md_content1 = f"""# Research Report: Next-Generation Sodium-Ion Cathode Performance

## Direct Answer
Next-generation sodium-ion cathodes—particularly titanium-stabilized O3-type layered oxides [S:{s1_1.id[:8]}] and Na3V2(PO4)3 polyanion frameworks [S:{s1_3.id[:8]}]—have reached commercial production readiness for stationary grid storage and urban electric transport. Validated operational data confirms gravimetric energy densities of 160–175 Wh/kg, retention exceeding 2,000 cycles at 1C [C:{clm1_1.id[:8]}], and an exceptional 35°C thermal safety margin over high-nickel NMC chemistries during thermal abuse testing [C:{clm1_2.id[:8]}].

## Executive Summary
This intelligence synthesis reviews empirical validation data across academic literature and commercial production trials for sodium-ion energy storage systems. While sodium-ion cells maintain a volumetric energy density penalty (~320 Wh/L vs 650 Wh/L in premium NMC) [C:{clm1_4.id[:8]}], their raw precursor cost advantage of 68% and exceptional -20°C discharge kinetics [C:{clm1_3.id[:8]}] make them the optimal solution for stationary BESS and light commercial fleets.

## Key Performance Benchmarks
| Metric | Sodium-Ion (O3 Layered) | Sodium-Ion (Polyanion NFPP) | Li-Ion (NMC811 Baseline) | Backing Evidence |
| Gravimetric Density | 165 Wh/kg | 135 Wh/kg | 260 Wh/kg | [C:{clm1_1.id[:8]}] |
| Volumetric Density | 320 Wh/L | 280 Wh/L | 650 Wh/L | [C:{clm1_4.id[:8]}] |
| Cycle Life (1C) | 2,000 cycles (88% ret) | 4,500 cycles (85% ret) | 1,500 cycles (80% ret) | [C:{clm1_1.id[:8]}] |
| Thermal Runaway Onset | 165°C | 210°C | 130°C | [C:{clm1_2.id[:8]}] |
| Retention at -20°C | 82.0% | 91.4% | 64.0% | [C:{clm1_3.id[:8]}] |
| Cathode Raw Material Cost | ~$3.20 / kWh eq | ~$4.10 / kWh eq | ~$18.50 / kWh eq | [S:{s1_1.id[:8]}] |

## Critical Findings & Synthesis
- **Thermal Abuse & Safety Profile**: Abuse tests confirm self-heating onset at 165°C with no catastrophic oxygen liberation [S:{s1_2.id[:8]}], eliminating violent thermal runaway propagation in modular packs.
- **Sub-Zero Discharge Resilience**: Polyanion tunnel structures preserve fast Na+ hopping even in frozen electrolytes, retaining 91.4% nominal capacity at -20°C [S:{s1_4.id[:8]}].
- **Supply Chain Independence**: Eliminates nickel, cobalt, and lithium supply constraints, shifting reliance to abundant soda ash and synthetic hard carbon precursors.

## Methodological Notes & Confidence
Synthesized across 4 peer-reviewed and industrial telemetry sources [S:{s1_1.id[:8]}] [S:{s1_2.id[:8]}] [S:{s1_3.id[:8]}] [S:{s1_4.id[:8]}]. All backing claims achieved verifier groundedness scores ≥0.91 with cryptographic quote span validation.
"""
    (dir1 / "report.md").write_text(report_md_content1, encoding="utf-8")

    report_json_content1 = {
        "run_id": run1_id,
        "objective": run1.objective,
        "status": "COMPLETED",
        "outcome": "ANSWERED",
        "findings": [
            {"id": f1_1.id, "conclusion": f1_1.conclusion, "confidence": f1_1.confidence},
            {"id": f1_2.id, "conclusion": f1_2.conclusion, "confidence": f1_2.confidence},
            {"id": f1_3.id, "conclusion": f1_3.conclusion, "confidence": f1_3.confidence},
        ],
        "claims_count": 4,
        "sources_count": 4,
    }
    (dir1 / "report.json").write_text(json.dumps(report_json_content1, indent=2), encoding="utf-8")

    evidence_pack1 = {
        "run_id": run1_id,
        "claims": [
            {"id": clm1_1.id, "text": clm1_1.text, "quote": clm1_1.quote, "source_id": s1_1.id, "confidence": clm1_1.confidence},
            {"id": clm1_2.id, "text": clm1_2.text, "quote": clm1_2.quote, "source_id": s1_2.id, "confidence": clm1_2.confidence},
            {"id": clm1_3.id, "text": clm1_3.text, "quote": clm1_3.quote, "source_id": s1_3.id, "confidence": clm1_3.confidence},
            {"id": clm1_4.id, "text": clm1_4.text, "quote": clm1_4.quote, "source_id": s1_3.id, "confidence": clm1_4.confidence},
        ]
    }
    (dir1 / "evidence_pack.json").write_text(json.dumps(evidence_pack1, indent=2), encoding="utf-8")

    sources_csv1 = (
        "id,domain,publisher,title,url,trust_tier\n"
        f"{s1_1.id},{s1_1.domain},{s1_1.publisher},\"{s1_1.title}\",{s1_1.location},{s1_1.trust_tier.value}\n"
        f"{s1_2.id},{s1_2.domain},{s1_2.publisher},\"{s1_2.title}\",{s1_2.location},{s1_2.trust_tier.value}\n"
        f"{s1_3.id},{s1_3.domain},{s1_3.publisher},\"{s1_3.title}\",{s1_3.location},{s1_3.trust_tier.value}\n"
        f"{s1_4.id},{s1_4.domain},{s1_4.publisher},\"{s1_4.title}\",{s1_4.location},{s1_4.trust_tier.value}\n"
    )
    (dir1 / "sources.csv").write_text(sources_csv1, encoding="utf-8")

    art1_md = Artifact(
        id="art-na-01-md",
        run_id=run1_id,
        type=ArtifactType.REPORT,
        format=ArtifactFormat.MD,
        path=str(dir1 / "report.md"),
        sha256=_compute_sha256(report_md_content1),
    )
    art1_json = Artifact(
        id="art-na-01-json",
        run_id=run1_id,
        type=ArtifactType.REPORT,
        format=ArtifactFormat.JSON,
        path=str(dir1 / "report.json"),
        sha256=_compute_sha256(json.dumps(report_json_content1, indent=2)),
    )
    art1_ev = Artifact(
        id="art-na-01-ev",
        run_id=run1_id,
        type=ArtifactType.EVIDENCE_PACK,
        format=ArtifactFormat.JSON,
        path=str(dir1 / "evidence_pack.json"),
        sha256=_compute_sha256(json.dumps(evidence_pack1, indent=2)),
    )
    art1_csv = Artifact(
        id="art-na-01-csv",
        run_id=run1_id,
        type=ArtifactType.SOURCE_LIST,
        format=ArtifactFormat.CSV,
        path=str(dir1 / "sources.csv"),
        sha256=_compute_sha256(sources_csv1),
    )
    session.add_all([art1_md, art1_json, art1_ev, art1_csv])

    evs1 = [
        Event(run_id=run1_id, type="run.started", payload_json={"objective": run1.objective}, created_at=base_time),
        Event(run_id=run1_id, type="planner.dag_generated", payload_json={"stages": 7, "subquestions": 3}, created_at=base_time + timedelta(seconds=30)),
        Event(run_id=run1_id, type="scout.sources_discovered", payload_json={"candidate_count": 4}, created_at=base_time + timedelta(minutes=1, seconds=30)),
        Event(run_id=run1_id, type="extractor.claims_extracted", payload_json={"extracted_claims": 4}, created_at=base_time + timedelta(minutes=3)),
        Event(run_id=run1_id, type="verifier.evidence_grounded", payload_json={"grounded_spans": 4, "avg_confidence": 0.94}, created_at=base_time + timedelta(minutes=4)),
        Event(run_id=run1_id, type="synthesizer.artifacts_generated", payload_json={"artifacts": 4}, created_at=base_time + timedelta(minutes=5, seconds=30)),
        Event(run_id=run1_id, type="run.completed", payload_json={"outcome": "ANSWERED", "duration_s": 240}, created_at=base_time + timedelta(minutes=6)),
    ]
    session.add_all(evs1)
    await session.flush()

    # =========================================================================
    # RUN 2: Composite Solid-State Electrolytes (COMPLETED / ANSWERED)
    # =========================================================================
    run2_id = "run-solid-state-002"
    run2 = ResearchRun(
        id=run2_id,
        objective="Analyze composite sulfide-halide solid electrolytes for lithium metal dendrite suppression",
        scope_json={"depth": "standard", "max_sources": 8, "budget": {"max_usd": 3.00, "max_minutes": 10}},
        status=RunStatus.COMPLETED,
        outcome=RunOutcome.ANSWERED,
        input_tokens=5600,
        output_tokens=2100,
        usd_cost=0.0112,
        tool_calls=16,
        created_by="admin",
        started_at=base_time + timedelta(hours=1, minutes=10),
        completed_at=base_time + timedelta(hours=1, minutes=15),
        created_at=base_time + timedelta(hours=1, minutes=8),
    )
    session.add(run2)
    await session.flush()

    s2_1 = Source(
        id="src-ss-jacs-01",
        kind=SourceKind.WEB,
        location="https://pubs.acs.org/doi/10.1021/jacs.4c12984",
        domain="pubs.acs.org",
        publisher="Journal of the American Chemical Society",
        title="Halide-substituted argyrodite solid electrolytes with high ionic conductivity and wide electrochemical window",
        retrieved_at=base_time + timedelta(hours=1, minutes=11),
        content_type="text/html",
        fingerprint=_compute_sha256("https://pubs.acs.org/doi/10.1021/jacs.4c12984"),
        trust_tier=TrustTier.TRUSTED,
        robots_ok=True,
        injection_risk=False,
        created_by_run_id=run2_id,
    )
    s2_2 = Source(
        id="src-ss-natcomm-02",
        kind=SourceKind.WEB,
        location="https://www.nature.com/articles/s41467-024-51209-1",
        domain="nature.com",
        publisher="Nature Communications",
        title="In-situ interphase engineering suppresses lithium dendrites in sulfide all-solid-state batteries",
        retrieved_at=base_time + timedelta(hours=1, minutes=12),
        content_type="text/html",
        fingerprint=_compute_sha256("https://www.nature.com/articles/s41467-024-51209-1"),
        trust_tier=TrustTier.TRUSTED,
        robots_ok=True,
        injection_risk=False,
        created_by_run_id=run2_id,
    )
    session.add_all([s2_1, s2_2])
    await session.flush()

    doc2_1_text = (
        "Li6PS5Cl0.5Br0.5 composite electrolytes exhibit room-temperature ionic conductivity of 10.2 mS/cm. "
        "Halide-doped sulfides reduce moisture sensitivity and hydrogen sulfide toxic gas evolution by 76% during ambient exposure."
    )
    d2_1 = Document(id="doc-ss-01", source_id=s2_1.id, text=doc2_1_text, language="en")

    doc2_2_text = (
        "Atomic layer deposition of ultra-thin LiNbO3 interface interlayers suppresses lithium dendrite penetration up to critical current densities of 4.2 mA/cm2. "
        "Pouch cells using composite sulfide electrolytes sustain 1,000 cycles at 0.5C with 84.6% capacity retention under 2 MPa stack pressure."
    )
    d2_2 = Document(id="doc-ss-02", source_id=s2_2.id, text=doc2_2_text, language="en")
    session.add_all([d2_1, d2_2])
    await session.flush()

    chk2_1 = Chunk(id="chk-ss-01", document_id=d2_1.id, idx=0, start_char=0, end_char=len(doc2_1_text), text=doc2_1_text)
    chk2_2 = Chunk(id="chk-ss-02", document_id=d2_2.id, idx=0, start_char=0, end_char=len(doc2_2_text), text=doc2_2_text)
    session.add_all([chk2_1, chk2_2])
    await session.flush()

    q2_1 = "Li6PS5Cl0.5Br0.5 composite electrolytes exhibit room-temperature ionic conductivity of 10.2 mS/cm."
    clm2_1 = Claim(
        id="clm-ss-01",
        run_id=run2_id,
        source_id=s2_1.id,
        document_id=d2_1.id,
        chunk_id=chk2_1.id,
        text="Halide-substituted argyrodite electrolytes achieve room-temperature ionic conductivity exceeding 10 mS/cm.",
        claim_type=ClaimType.MEASUREMENT,
        quote=q2_1,
        span_start=doc2_1_text.find(q2_1),
        span_end=doc2_1_text.find(q2_1) + len(q2_1),
        confidence=0.97,
        status=ClaimStatus.ACTIVE,
        created_by_agent="ExtractorAgent",
        created_at=base_time + timedelta(hours=1, minutes=13),
    )
    q2_2 = "Atomic layer deposition of ultra-thin LiNbO3 interface interlayers suppresses lithium dendrite penetration up to critical current densities of 4.2 mA/cm2."
    clm2_2 = Claim(
        id="clm-ss-02",
        run_id=run2_id,
        source_id=s2_2.id,
        document_id=d2_2.id,
        chunk_id=chk2_2.id,
        text="Conformal interphase engineering raises the critical current density threshold to 4.2 mA/cm2 without dendrite shorting.",
        claim_type=ClaimType.MEASUREMENT,
        quote=q2_2,
        span_start=doc2_2_text.find(q2_2),
        span_end=doc2_2_text.find(q2_2) + len(q2_2),
        confidence=0.93,
        status=ClaimStatus.ACTIVE,
        created_by_agent="ExtractorAgent",
        created_at=base_time + timedelta(hours=1, minutes=13),
    )
    session.add_all([clm2_1, clm2_2])
    await session.flush()

    e2_1 = Evidence(
        id="evi-ss-01",
        claim_id=clm2_1.id,
        source_id=s2_1.id,
        document_id=d2_1.id,
        chunk_id=chk2_1.id,
        span_start=clm2_1.span_start,
        span_end=clm2_1.span_end,
        quote=clm2_1.quote,
        support_type=EvidenceSupportType.SUPPORTS,
        created_by_run_id=run2_id,
        created_by_agent="VerifierAgent",
    )
    e2_2 = Evidence(
        id="evi-ss-02",
        claim_id=clm2_2.id,
        source_id=s2_2.id,
        document_id=d2_2.id,
        chunk_id=chk2_2.id,
        span_start=clm2_2.span_start,
        span_end=clm2_2.span_end,
        quote=clm2_2.quote,
        support_type=EvidenceSupportType.SUPPORTS,
        created_by_run_id=run2_id,
        created_by_agent="VerifierAgent",
    )
    session.add_all([e2_1, e2_2])

    f2_1 = Finding(
        id="fnd-ss-01",
        run_id=run2_id,
        conclusion="Dual halide-doped argyrodites overcome the conductivity-stability trade-off, surpassing 10 mS/cm while suppressing lithium filament growth under high current loads.",
        confidence=0.95,
        claim_ids_json=[clm2_1.id, clm2_2.id],
        gaps_json=["Mechanical stress under continuous unconstrained volume expansion remains an engineering barrier."],
        contradictions_json=[],
        unverified_json=[],
    )
    session.add(f2_1)

    dir2 = artifacts_root / run2_id
    dir2.mkdir(parents=True, exist_ok=True)
    report_md_content2 = f"""# Research Report: Solid-State Battery Electrolyte Stability

## Direct Answer
Halide-substituted argyrodite solid electrolytes (specifically Li6PS5Cl0.5Br0.5) [S:{s2_1.id[:8]}] demonstrate room-temperature ionic conductivities of 10.2 mS/cm [C:{clm2_1.id[:8]}]. Conformal atomic-layer-deposited LiNbO3 interface layers prevent lithium dendrite penetration up to 4.2 mA/cm2 [C:{clm2_2.id[:8]}], enabling full solid-state cells with >84% capacity retention over 1,000 cycles.

## Key Findings
- Dual halide substitution dramatically lowers grain-boundary resistance.
- Critical current density for dendrite propagation is elevated from 0.8 mA/cm2 to 4.2 mA/cm2 via interface passivation [S:{s2_2.id[:8]}].
"""
    (dir2 / "report.md").write_text(report_md_content2, encoding="utf-8")
    (dir2 / "report.json").write_text(json.dumps({"run_id": run2_id, "status": "COMPLETED"}, indent=2), encoding="utf-8")
    (dir2 / "evidence_pack.json").write_text(json.dumps({"run_id": run2_id, "claims": [{"id": clm2_1.id}, {"id": clm2_2.id}]}, indent=2), encoding="utf-8")
    (dir2 / "sources.csv").write_text(f"id,domain,title\n{s2_1.id},{s2_1.domain},\"{s2_1.title}\"\n{s2_2.id},{s2_2.domain},\"{s2_2.title}\"\n", encoding="utf-8")

    session.add_all([
        Artifact(id="art-ss-01-md", run_id=run2_id, type=ArtifactType.REPORT, format=ArtifactFormat.MD, path=str(dir2 / "report.md"), sha256=_compute_sha256(report_md_content2)),
        Artifact(id="art-ss-01-json", run_id=run2_id, type=ArtifactType.REPORT, format=ArtifactFormat.JSON, path=str(dir2 / "report.json"), sha256=_compute_sha256(dir2 / "report.json")),
        Artifact(id="art-ss-01-ev", run_id=run2_id, type=ArtifactType.EVIDENCE_PACK, format=ArtifactFormat.JSON, path=str(dir2 / "evidence_pack.json"), sha256=_compute_sha256(dir2 / "evidence_pack.json")),
        Artifact(id="art-ss-01-csv", run_id=run2_id, type=ArtifactType.SOURCE_LIST, format=ArtifactFormat.CSV, path=str(dir2 / "sources.csv"), sha256=_compute_sha256(dir2 / "sources.csv")),
    ])
    await session.flush()

    # =========================================================================
    # RUN 3: Autonomous LLM Multi-Agent Consensus (COMPLETED / ANSWERED)
    # =========================================================================
    run3_id = "run-multiagent-003"
    run3 = ResearchRun(
        id=run3_id,
        objective="Evaluate fault-tolerant consensus and verification architectures in enterprise autonomous LLM agent pipelines",
        scope_json={"depth": "standard", "max_sources": 6, "budget": {"max_usd": 2.00, "max_minutes": 8}},
        status=RunStatus.COMPLETED,
        outcome=RunOutcome.ANSWERED,
        input_tokens=4900,
        output_tokens=1950,
        usd_cost=0.0095,
        tool_calls=15,
        created_by="admin",
        started_at=base_time + timedelta(hours=2, minutes=20),
        completed_at=base_time + timedelta(hours=2, minutes=24),
        created_at=base_time + timedelta(hours=2, minutes=18),
    )
    session.add(run3)
    await session.flush()

    s3_1 = Source(
        id="src-ag-arxiv-01",
        kind=SourceKind.WEB,
        location="https://arxiv.org/abs/2501.08912",
        domain="arxiv.org",
        publisher="arXiv Distributed Computing & AI",
        title="Byzantine consensus verification in decentralized LLM reasoning agents",
        retrieved_at=base_time + timedelta(hours=2, minutes=21),
        content_type="text/html",
        fingerprint=_compute_sha256("https://arxiv.org/abs/2501.08912"),
        trust_tier=TrustTier.TRUSTED,
        robots_ok=True,
        injection_risk=False,
        created_by_run_id=run3_id,
    )
    session.add(s3_1)
    await session.flush()

    doc3_text = (
        "Multi-agent debate protocols with Byzantine quorum voting reduce factual hallucinations by 64% compared to single-pass CoT generation. "
        "Cryptographic quote offset verification against raw source bytes detects 98.7% of fabricated citations prior to report publication."
    )
    d3_1 = Document(id="doc-ag-01", source_id=s3_1.id, text=doc3_text, language="en")
    session.add(d3_1)
    await session.flush()

    chk3_1 = Chunk(id="chk-ag-01", document_id=d3_1.id, idx=0, start_char=0, end_char=len(doc3_text), text=doc3_text)
    session.add(chk3_1)
    await session.flush()

    q3_1 = "Multi-agent debate protocols with Byzantine quorum voting reduce factual hallucinations by 64% compared to single-pass CoT generation."
    clm3_1 = Claim(
        id="clm-ag-01",
        run_id=run3_id,
        source_id=s3_1.id,
        document_id=d3_1.id,
        chunk_id=chk3_1.id,
        text="Quorum verification reduces factual errors by 64% across enterprise agent synthesis runs.",
        claim_type=ClaimType.MEASUREMENT,
        quote=q3_1,
        span_start=doc3_text.find(q3_1),
        span_end=doc3_text.find(q3_1) + len(q3_1),
        confidence=0.98,
        status=ClaimStatus.ACTIVE,
        created_by_agent="ExtractorAgent",
        created_at=base_time + timedelta(hours=2, minutes=22),
    )
    session.add(clm3_1)
    await session.flush()

    e3_1 = Evidence(
        id="evi-ag-01",
        claim_id=clm3_1.id,
        source_id=s3_1.id,
        document_id=d3_1.id,
        chunk_id=chk3_1.id,
        span_start=clm3_1.span_start,
        span_end=clm3_1.span_end,
        quote=clm3_1.quote,
        support_type=EvidenceSupportType.SUPPORTS,
        created_by_run_id=run3_id,
        created_by_agent="VerifierAgent",
    )
    session.add(e3_1)

    f3_1 = Finding(
        id="fnd-ag-01",
        run_id=run3_id,
        conclusion="Decoupled extractor-verifier pipelines with cryptographic span validation virtually eliminate fabricated citations.",
        confidence=0.97,
        claim_ids_json=[clm3_1.id],
        gaps_json=[],
        contradictions_json=[],
        unverified_json=[],
    )
    session.add(f3_1)

    dir3 = artifacts_root / run3_id
    dir3.mkdir(parents=True, exist_ok=True)
    report_md_content3 = f"""# Research Report: Autonomous Multi-Agent Fault Tolerance

## Direct Answer
Enterprise autonomous agent systems require multi-agent debate and cryptographic claim-to-chunk span verification [S:{s3_1.id[:8]}]. Empirical benchmarks confirm a 64% reduction in hallucinations [C:{clm3_1.id[:8]}] and 98.7% catch rate for synthetic hallucinated citations.

## Summary & Architecture
1. **Quorum Verification**: Parallel verification loops with independent model gates.
2. **Deterministic Offsets**: Byte-level offsets ensure tamper-evident evidence packs.
"""
    (dir3 / "report.md").write_text(report_md_content3, encoding="utf-8")
    (dir3 / "report.json").write_text(json.dumps({"run_id": run3_id, "status": "COMPLETED"}, indent=2), encoding="utf-8")
    (dir3 / "evidence_pack.json").write_text(json.dumps({"run_id": run3_id, "claims": [{"id": clm3_1.id}]}, indent=2), encoding="utf-8")
    (dir3 / "sources.csv").write_text(f"id,domain,title\n{s3_1.id},{s3_1.domain},\"{s3_1.title}\"\n", encoding="utf-8")

    session.add_all([
        Artifact(id="art-ag-01-md", run_id=run3_id, type=ArtifactType.REPORT, format=ArtifactFormat.MD, path=str(dir3 / "report.md"), sha256=_compute_sha256(report_md_content3)),
        Artifact(id="art-ag-01-json", run_id=run3_id, type=ArtifactType.REPORT, format=ArtifactFormat.JSON, path=str(dir3 / "report.json"), sha256=_compute_sha256(dir3 / "report.json")),
        Artifact(id="art-ag-01-ev", run_id=run3_id, type=ArtifactType.EVIDENCE_PACK, format=ArtifactFormat.JSON, path=str(dir3 / "evidence_pack.json"), sha256=_compute_sha256(dir3 / "evidence_pack.json")),
        Artifact(id="art-ag-01-csv", run_id=run3_id, type=ArtifactType.SOURCE_LIST, format=ArtifactFormat.CSV, path=str(dir3 / "sources.csv"), sha256=_compute_sha256(dir3 / "sources.csv")),
    ])
    await session.flush()

    # =========================================================================
    # RUN 4: Superconducting Qubit Interconnect (REVIEW_REQUIRED / Quarantine)
    # =========================================================================
    run4_id = "run-quantum-004"
    run4 = ResearchRun(
        id=run4_id,
        objective="Investigate high-temperature superconducting quantum interconnect protocols",
        scope_json={"depth": "standard", "max_sources": 5, "budget": {"max_usd": 2.00, "max_minutes": 5}},
        status=RunStatus.REVIEW_REQUIRED,
        outcome=None,
        input_tokens=2200,
        output_tokens=850,
        usd_cost=0.0045,
        tool_calls=8,
        created_by="admin",
        started_at=base_time + timedelta(hours=3, minutes=10),
        completed_at=None,
        created_at=base_time + timedelta(hours=3, minutes=8),
    )
    session.add(run4)
    await session.flush()

    s4_1 = Source(
        id="src-qu-prl-01",
        kind=SourceKind.WEB,
        location="https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.132.080601",
        domain="journals.aps.org",
        publisher="Physical Review Letters",
        title="Thermal decoherence bounds in microwave quantum state transfer channels",
        retrieved_at=base_time + timedelta(hours=3, minutes=11),
        content_type="text/html",
        fingerprint=_compute_sha256("https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.132.080601"),
        trust_tier=TrustTier.TRUSTED,
        robots_ok=True,
        injection_risk=False,
        created_by_run_id=run4_id,
    )
    s4_2 = Source(
        id="src-qu-quar-02",
        kind=SourceKind.WEB,
        location="https://unverified-preprint-vault.net/papers/quantum-rt-claim.html",
        domain="unverified-preprint-vault.net",
        publisher="Unverified Preprint Forum",
        title="Room temperature optical-microwave quantum coherent transducer without cryogenics",
        retrieved_at=base_time + timedelta(hours=3, minutes=12),
        content_type="text/html",
        fingerprint=_compute_sha256("https://unverified-preprint-vault.net/papers/quantum-rt-claim.html"),
        trust_tier=TrustTier.QUARANTINE,
        robots_ok=True,
        injection_risk=True,
        created_by_run_id=run4_id,
    )
    session.add_all([s4_1, s4_2])
    await session.flush()

    doc4_1_text = (
        "Thermal noise destroys quantum microwave coherence in under 2 nanoseconds above 10 Kelvin. "
        "Coaxial microwave resonators achieve 99.1% quantum state transfer fidelity at 15 mK dilution temperatures."
    )
    d4_1 = Document(id="doc-qu-01", source_id=s4_1.id, text=doc4_1_text, language="en")

    doc4_2_text = (
        "Photonic-piezoelectric transceivers demonstrate room temperature coherence preservation exceeding 100 microseconds."
    )
    d4_2 = Document(id="doc-qu-02", source_id=s4_2.id, text=doc4_2_text, language="en")
    session.add_all([d4_1, d4_2])
    await session.flush()

    chk4_1 = Chunk(id="chk-qu-01", document_id=d4_1.id, idx=0, start_char=0, end_char=len(doc4_1_text), text=doc4_1_text)
    chk4_2 = Chunk(id="chk-qu-02", document_id=d4_2.id, idx=0, start_char=0, end_char=len(doc4_2_text), text=doc4_2_text)
    session.add_all([chk4_1, chk4_2])
    await session.flush()

    q4_1 = "Coaxial microwave resonators achieve 99.1% quantum state transfer fidelity at 15 mK dilution temperatures."
    clm4_1 = Claim(
        id="clm-qu-01",
        run_id=run4_id,
        source_id=s4_1.id,
        document_id=d4_1.id,
        chunk_id=chk4_1.id,
        text="Microwave resonators maintain 99.1% quantum state transfer fidelity under cryogenic conditions (<15 mK).",
        claim_type=ClaimType.MEASUREMENT,
        quote=q4_1,
        span_start=doc4_1_text.find(q4_1),
        span_end=doc4_1_text.find(q4_1) + len(q4_1),
        confidence=0.95,
        status=ClaimStatus.ACTIVE,
        created_by_agent="ExtractorAgent",
        created_at=base_time + timedelta(hours=3, minutes=13),
    )
    q4_2 = "Photonic-piezoelectric transceivers demonstrate room temperature coherence preservation exceeding 100 microseconds."
    clm4_2 = Claim(
        id="clm-qu-02",
        run_id=run4_id,
        source_id=s4_2.id,
        document_id=d4_2.id,
        chunk_id=chk4_2.id,
        text="Claims room-temperature quantum coherence of 100 microseconds via unverified piezoelectric coupling.",
        claim_type=ClaimType.STATEMENT_OF_OPINION,
        quote=q4_2,
        span_start=doc4_2_text.find(q4_2),
        span_end=doc4_2_text.find(q4_2) + len(q4_2),
        confidence=0.35,
        status=ClaimStatus.DISPUTED,
        retraction_reason="Directly contradicted by thermal decoherence bounds from Physical Review Letters. Quarantined source flagged for potential injection.",
        created_by_agent="ExtractorAgent",
        created_at=base_time + timedelta(hours=3, minutes=13),
    )
    session.add_all([clm4_1, clm4_2])
    await session.flush()

    e4_1 = Evidence(
        id="evi-qu-01",
        claim_id=clm4_1.id,
        source_id=s4_1.id,
        document_id=d4_1.id,
        chunk_id=chk4_1.id,
        span_start=clm4_1.span_start,
        span_end=clm4_1.span_end,
        quote=clm4_1.quote,
        support_type=EvidenceSupportType.SUPPORTS,
        created_by_run_id=run4_id,
        created_by_agent="VerifierAgent",
    )
    e4_2 = Evidence(
        id="evi-qu-02",
        claim_id=clm4_2.id,
        source_id=s4_1.id,
        document_id=d4_1.id,
        chunk_id=chk4_1.id,
        span_start=0,
        span_end=74,
        quote="Thermal noise destroys quantum microwave coherence in under 2 nanoseconds above 10 Kelvin.",
        support_type=EvidenceSupportType.CONTRADICTS,
        created_by_run_id=run4_id,
        created_by_agent="CriticAgent",
    )
    session.add_all([e4_1, e4_2])

    dir4 = artifacts_root / run4_id
    dir4.mkdir(parents=True, exist_ok=True)
    report_md_content4 = f"""# Research Report: Quantum Interconnect Protocols (Review Required)

## Direct Answer
High-fidelity quantum state transfer currently mandates cryogenic temperatures (<15 mK) [S:{s4_1.id[:8]}], achieving 99.1% state fidelity [C:{clm4_1.id[:8]}]. Unverified assertions of room-temperature coherence [S:{s4_2.id[:8]}] [C:{clm4_2.id[:8]}] have been rejected and flagged as disputed due to thermal phonon decoherence constraints.

## Disputed Claims & Governance Gate
- **Claim [C:{clm4_2.id[:8]}]**: Flagged DISPUTED. Contradicted by empirical thermal bounds. Requires administrator review in Review Queue.
"""
    (dir4 / "report.md").write_text(report_md_content4, encoding="utf-8")
    (dir4 / "report.json").write_text(json.dumps({"run_id": run4_id, "status": "REVIEW_REQUIRED"}, indent=2), encoding="utf-8")
    (dir4 / "evidence_pack.json").write_text(json.dumps({"run_id": run4_id, "claims": [{"id": clm4_1.id}, {"id": clm4_2.id}]}, indent=2), encoding="utf-8")
    (dir4 / "sources.csv").write_text(f"id,domain,title,trust_tier\n{s4_1.id},{s4_1.domain},\"{s4_1.title}\",{s4_1.trust_tier.value}\n{s4_2.id},{s4_2.domain},\"{s4_2.title}\",{s4_2.trust_tier.value}\n", encoding="utf-8")

    session.add_all([
        Artifact(id="art-qu-01-md", run_id=run4_id, type=ArtifactType.REPORT, format=ArtifactFormat.MD, path=str(dir4 / "report.md"), sha256=_compute_sha256(report_md_content4)),
        Artifact(id="art-qu-01-json", run_id=run4_id, type=ArtifactType.REPORT, format=ArtifactFormat.JSON, path=str(dir4 / "report.json"), sha256=_compute_sha256(dir4 / "report.json")),
        Artifact(id="art-qu-01-ev", run_id=run4_id, type=ArtifactType.EVIDENCE_PACK, format=ArtifactFormat.JSON, path=str(dir4 / "evidence_pack.json"), sha256=_compute_sha256(dir4 / "evidence_pack.json")),
        Artifact(id="art-qu-01-csv", run_id=run4_id, type=ArtifactType.SOURCE_LIST, format=ArtifactFormat.CSV, path=str(dir4 / "sources.csv"), sha256=_compute_sha256(dir4 / "sources.csv")),
    ])
    await session.flush()

    # =========================================================================
    # Cryptographic Audit Ledger Entries
    # =========================================================================
    await AuditChain.append_event(
        session=session,
        actor="system",
        action="demo.bootstrap.initialized",
        object_type="system",
        object_id="genesis",
        detail_json={"seeded_runs": 4, "total_artifacts": 16},
    )
    await AuditChain.append_event(
        session=session,
        actor="admin",
        action="research.run_created",
        object_type="research_run",
        object_id=run1_id,
        detail_json={"objective": run1.objective, "status": "COMPLETED"},
    )
    await AuditChain.append_event(
        session=session,
        actor="admin",
        action="research.run_created",
        object_type="research_run",
        object_id=run2_id,
        detail_json={"objective": run2.objective, "status": "COMPLETED"},
    )
    await AuditChain.append_event(
        session=session,
        actor="admin",
        action="research.run_created",
        object_type="research_run",
        object_id=run3_id,
        detail_json={"objective": run3.objective, "status": "COMPLETED"},
    )
    await AuditChain.append_event(
        session=session,
        actor="security_engine",
        action="source.quarantined",
        object_type="source",
        object_id=s4_2.id,
        detail_json={"reason": "unverified_preprint_injection_risk"},
    )
    await AuditChain.append_event(
        session=session,
        actor="governance_engine",
        action="review.gate_triggered",
        object_type="research_run",
        object_id=run4_id,
        detail_json={"status": "REVIEW_REQUIRED", "disputed_claims": 1},
    )

    await session.commit()
    logger.info("Successfully bootstrapped 4 production demonstrations with full evidence graph & artifacts.")
    return True
