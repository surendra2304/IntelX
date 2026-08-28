"""INTELX Artifact Generator, Atomic Storage Manager, and Versioned Exporter."""

import csv
import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import ArtifactFormat, ArtifactType
from intelx.db.models import Artifact, Claim, Evidence, ResearchRun, Source

logger = logging.getLogger(__name__)


class ReportArtifactMeta(BaseModel):
    """Execution metadata included in versioned machine-readable report."""

    run_id: str
    objective: str
    status: str
    outcome: str | None
    started_at: str | None
    completed_at: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    usd_cost: float = 0.0
    tool_calls: int = 0


class ReportArtifact(BaseModel):
    """Schema-versioned v1.0 machine-readable intelligence report."""

    schema_version: str = Field(default="v1.0")
    meta: ReportArtifactMeta
    executive_answer: str
    overall_confidence_label: str
    key_findings: list[dict[str, Any]] = Field(default_factory=list)
    unverified_findings: list[dict[str, Any]] = Field(default_factory=list)
    claims_referenced: list[dict[str, Any]] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    degradations: list[str] = Field(default_factory=list)


def atomic_write_file(path: Path, content: str | bytes) -> str:
    """Write content to file atomically using a temporary sibling file and return SHA256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")

    if isinstance(content, str):
        raw_bytes = content.encode("utf-8")
        temp_path.write_text(content, encoding="utf-8")
    else:
        raw_bytes = content
        temp_path.write_bytes(content)

    temp_path.replace(path)
    return hashlib.sha256(raw_bytes).hexdigest()


async def generate_and_save_artifacts(
    session: AsyncSession,
    run: ResearchRun,
    report_markdown: str,
    grounded_findings: list[dict[str, Any]],
    unverified_findings: list[dict[str, Any]],
    claims: list[Claim],
    sources: list[Source],
    evidence_items: list[Evidence],
    gaps: list[str] | None = None,
    contradictions: list[dict[str, Any]] | None = None,
    degradations: list[str] | None = None,
    overall_confidence_label: str = "Moderate",
    base_dir: Path | None = None,
) -> list[Artifact]:
    """Generate all 4 research artifacts, write atomically to disk, and register in database."""
    run_dir = (base_dir or Path("data/artifacts")) / run.id
    run_dir.mkdir(parents=True, exist_ok=True)

    artifacts_created: list[Artifact] = []

    # 1. report.md
    report_md_path = run_dir / "report.md"
    md_sha256 = atomic_write_file(report_md_path, report_markdown)
    art_md = Artifact(
        run_id=run.id,
        type=ArtifactType.REPORT,
        format=ArtifactFormat.MD,
        path=str(report_md_path),
        schema_version="v1.0",
        sha256=md_sha256,
    )
    session.add(art_md)
    artifacts_created.append(art_md)

    # 2. report.json
    meta = ReportArtifactMeta(
        run_id=run.id,
        objective=run.objective,
        status=str(run.status),
        outcome=str(run.outcome) if run.outcome else None,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        usd_cost=run.usd_cost,
        tool_calls=run.tool_calls,
    )

    claims_ref = [
        {
            "id": c.id,
            "text": c.text,
            "claim_type": str(c.claim_type),
            "status": str(c.status),
            "confidence": c.confidence,
            "source_id": c.source_id,
        }
        for c in claims
    ]

    sources_ref = [
        {
            "id": s.id,
            "location": s.location,
            "domain": s.domain,
            "title": s.title,
            "trust_tier": str(s.trust_tier),
            "injection_risk": s.injection_risk,
        }
        for s in sources
    ]

    exec_ans = ""
    if "## Direct Answer" in report_markdown and "## Key Findings" in report_markdown:
        part = report_markdown.split("## Direct Answer")[1]
        exec_ans = part.split("## Key Findings")[0].strip()

    report_artifact_obj = ReportArtifact(
        schema_version="v1.0",
        meta=meta,
        executive_answer=exec_ans,
        overall_confidence_label=overall_confidence_label,
        key_findings=grounded_findings,
        unverified_findings=unverified_findings,
        claims_referenced=claims_ref,
        contradictions=contradictions or [],
        gaps=gaps or [],
        sources=sources_ref,
        degradations=degradations or [],
    )

    report_json_path = run_dir / "report.json"
    json_sha256 = atomic_write_file(report_json_path, report_artifact_obj.model_dump_json(indent=2))
    art_json = Artifact(
        run_id=run.id,
        type=ArtifactType.REPORT,
        format=ArtifactFormat.JSON,
        path=str(report_json_path),
        schema_version="v1.0",
        sha256=json_sha256,
    )
    session.add(art_json)
    artifacts_created.append(art_json)

    # 3. evidence_pack.json
    evidence_pack_data = {
        "schema_version": "v1.0",
        "run_id": run.id,
        "sources": [
            {
                "id": s.id,
                "kind": str(s.kind),
                "location": s.location,
                "title": s.title,
                "domain": s.domain,
                "fingerprint": s.fingerprint,
                "trust_tier": str(s.trust_tier),
            }
            for s in sources
        ],
        "claims": [
            {
                "id": c.id,
                "text": c.text,
                "quote": c.quote,
                "span_start": c.span_start,
                "span_end": c.span_end,
                "claim_type": str(c.claim_type),
                "confidence": c.confidence,
                "status": str(c.status),
                "source_id": c.source_id,
            }
            for c in claims
        ],
        "evidence_spans": [
            {
                "id": e.id,
                "claim_id": e.claim_id,
                "source_id": e.source_id,
                "span_start": e.span_start,
                "span_end": e.span_end,
                "quote": e.quote,
                "support_type": str(e.support_type),
            }
            for e in evidence_items
        ],
    }
    evidence_pack_path = run_dir / "evidence_pack.json"
    ev_sha256 = atomic_write_file(evidence_pack_path, json.dumps(evidence_pack_data, indent=2))
    art_ev = Artifact(
        run_id=run.id,
        type=ArtifactType.EVIDENCE_PACK,
        format=ArtifactFormat.JSON,
        path=str(evidence_pack_path),
        schema_version="v1.0",
        sha256=ev_sha256,
    )
    session.add(art_ev)
    artifacts_created.append(art_ev)

    # 4. sources.csv
    csv_output = io.StringIO()
    csv_writer = csv.writer(csv_output)
    csv_writer.writerow(
        [
            "id",
            "kind",
            "location",
            "domain",
            "publisher",
            "title",
            "trust_tier",
            "injection_risk",
            "retrieved_at",
        ]
    )
    for s in sources:
        csv_writer.writerow(
            [
                s.id,
                str(s.kind),
                s.location,
                s.domain or "",
                s.publisher or "",
                s.title or "",
                str(s.trust_tier),
                s.injection_risk,
                s.retrieved_at.isoformat() if s.retrieved_at else "",
            ]
        )

    sources_csv_path = run_dir / "sources.csv"
    csv_sha256 = atomic_write_file(sources_csv_path, csv_output.getvalue())
    art_csv = Artifact(
        run_id=run.id,
        type=ArtifactType.SOURCE_LIST,
        format=ArtifactFormat.CSV,
        path=str(sources_csv_path),
        schema_version="v1.0",
        sha256=csv_sha256,
    )
    session.add(art_csv)
    artifacts_created.append(art_csv)

    await session.flush()
    return artifacts_created
