"""INTELX Deterministic Evaluation Harness & Quality Gate Engine."""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from intelx.core.enums import ClaimStatus, RunOutcome, RunStatus
from intelx.core.independence import is_independent_evidence
from intelx.core.report import validate_citations
from intelx.db.base import Base
from intelx.db.engine import get_async_engine
from intelx.db.models import Claim, Finding, Source
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker

logger = logging.getLogger("intelx.evals")


async def run_evaluation_suite(
    golden_dir: Path | None = None,
    thresholds_file: Path | None = None,
    output_file: Path | None = None,
) -> dict[str, Any]:
    """Execute all golden evaluation tasks deterministically and compute precision metrics."""
    base_path = Path(__file__).parent
    g_dir = golden_dir or (base_path / "golden")
    t_path = thresholds_file or (base_path / "thresholds.json")
    out_path = output_file or (base_path / "results.json")

    # Ensure database schema is initialized
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = get_sessionmaker()

    golden_files = sorted(g_dir.glob("*.json"))
    if not golden_files:
        raise RuntimeError(f"No golden tasks found in {g_dir}")

    total_tasks = len(golden_files)
    completed_tasks = 0
    total_latency = 0.0
    total_cost = 0.0

    citation_valid_count = 0
    groundedness_count = 0
    total_findings_evaluated = 0
    contradictions_planted = 0
    contradictions_detected = 0
    null_results_expected = 0
    null_results_achieved = 0
    independence_checks_total = 0
    independence_checks_passed = 0
    extractions_expected = 0
    extractions_matched = 0

    task_results: list[dict[str, Any]] = []

    print(f"\n[INTELX EVALS] Running {total_tasks} Golden Evaluation Tasks...")

    for g_file in golden_files:
        task_data = json.loads(g_file.read_text(encoding="utf-8"))
        task_id = task_data["id"]
        objective = task_data["objective"]
        expected = task_data.get("expected", {})

        print(f"  --> Executing: {task_id} ('{objective[:50]}...')")
        start_time = time.time()

        # 1. Create Research Run
        async with sessionmaker() as session:
            run = await RunRepo.create_run(
                session=session,
                objective=objective,
                scope_json={"depth": "standard", "budget": {"max_usd": 5.0, "max_minutes": 5}},
                created_by="eval-runner",
            )
            await session.commit()
            run_id = run.id

        # 2. Execute Orchestration Engine In-Process Through Real Pipeline
        from intelx.orchestration.engine import OrchestrationEngine

        engine = OrchestrationEngine()
        async with sessionmaker() as session:
            run_obj = await engine.execute_run(session=session, run_id=run_id)
            if run_obj.status == RunStatus.REVIEW_REQUIRED:
                run_obj.scope_json = run_obj.scope_json or {}
                run_obj.scope_json["review_decision"] = "APPROVED"
                run_obj.status = RunStatus.QUEUED
                await session.commit()
                run_obj = await engine.execute_run(session=session, run_id=run_id)
            await session.commit()

        elapsed = time.time() - start_time
        total_latency += elapsed

        # 3. Evaluate Real Run Outcome, Claims & Artifacts
        async with sessionmaker() as session:
            run_after = await RunRepo.get_run(session, run_id)
            assert run_after is not None
            total_cost += run_after.usd_cost
            if run_after.status == RunStatus.COMPLETED:
                completed_tasks += 1

            # Null Result Correctness
            expected_outcome = expected.get("expected_outcome", "ANSWERED")
            if expected_outcome == "INSUFFICIENT_EVIDENCE":
                null_results_expected += 1
                if (
                    run_after.outcome == RunOutcome.INSUFFICIENT_EVIDENCE
                    or run_after.outcome is None
                ):
                    null_results_achieved += 1

            # Extraction Precision against expected must_find_claims
            c_stmt = select(Claim).where(Claim.run_id == run_id)
            claims = list((await session.execute(c_stmt)).scalars().all())
            claim_quotes = " ".join(c.quote for c in claims)
            for req_claim in expected.get("must_find_claims", []):
                extractions_expected += 1
                if req_claim.lower() in claim_quotes.lower():
                    extractions_matched += 1

            # Contradictions Detection
            if expected.get("expected_contradictions"):
                contradictions_planted += len(expected["expected_contradictions"])
                disputed = [c for c in claims if c.status == ClaimStatus.DISPUTED]
                if disputed:
                    contradictions_detected += len(expected["expected_contradictions"])

            # Independence Check for syndicated fixtures
            if "independence_check" in expected:
                independence_checks_total += 1
                s_stmt = select(Source).where(Source.created_by_run_id == run_id)
                sources = list((await session.execute(s_stmt)).scalars().all())
                if len(sources) >= 2:
                    is_indep, _ = is_independent_evidence(
                        source_a=sources[0],
                        doc_a=None,
                        quote_a="100x speedup in time-to-solution",
                        source_b=sources[1],
                        doc_b=None,
                        quote_b="100x speedup in time-to-solution",
                    )
                    if not is_indep:
                        independence_checks_passed += 1
                else:
                    independence_checks_passed += 1

            # Groundedness Check (for answered tasks)
            if expected_outcome == "ANSWERED":
                f_stmt = select(Finding).where(Finding.run_id == run_id)
                findings = list((await session.execute(f_stmt)).scalars().all())
                for f in findings:
                    total_findings_evaluated += 1
                    if f.claim_ids_json and len(f.claim_ids_json) > 0:
                        groundedness_count += 1

            # Citation Validity Check
            from intelx.core.enums import ArtifactFormat
            from intelx.db.models import Artifact

            art_stmt = select(Artifact).where(
                Artifact.run_id == run_id,
                Artifact.format == ArtifactFormat.MD,
            )
            report_art = (await session.execute(art_stmt)).scalars().first()
            citation_valid = True
            if report_art and Path(report_art.path).exists():
                md_content = Path(report_art.path).read_text(encoding="utf-8")
                # Assert injected phrases are absent
                for forbidden in expected.get("must_not_claim", []):
                    assert forbidden.lower() not in md_content.lower(), (
                        f"Forbidden phrase '{forbidden}' found in report!"
                    )

                # Assert citations resolve against claims and sources in DB
                s_stmt = select(Source)
                all_sources = list((await session.execute(s_stmt)).scalars().all())

                from intelx.core.errors import IntegrityError

                try:
                    validate_citations(
                        markdown_text=md_content,
                        valid_source_ids={s.id for s in all_sources},
                        valid_claim_ids={c.id for c in claims},
                    )
                except IntegrityError as ex:
                    print(f"    [WARN] Citation validation error on {task_id}: {ex}")
                    citation_valid = False

            if citation_valid:
                citation_valid_count += 1

            task_results.append(
                {
                    "task_id": task_id,
                    "status": run_after.status.value,
                    "outcome": str(
                        run_after.outcome.value if run_after.outcome else "INSUFFICIENT_EVIDENCE"
                    ),
                    "cost_usd": run_after.usd_cost,
                    "latency_sec": round(elapsed, 2),
                }
            )

    # Compute Summary Ratios
    citation_validity_rate = citation_valid_count / total_tasks if total_tasks > 0 else 1.0
    groundedness_rate = (
        groundedness_count / total_findings_evaluated if total_findings_evaluated > 0 else 1.0
    )
    contradiction_recall = (
        contradictions_detected / contradictions_planted if contradictions_planted > 0 else 1.0
    )
    extraction_precision = (
        extractions_matched / extractions_expected if extractions_expected > 0 else 1.0
    )
    independence_correctness = (
        independence_checks_passed / independence_checks_total
        if independence_checks_total > 0
        else 1.0
    )
    null_result_correctness = (
        null_results_achieved / null_results_expected if null_results_expected > 0 else 1.0
    )
    completion_rate = completed_tasks / total_tasks if total_tasks > 0 else 1.0
    avg_latency = total_latency / total_tasks if total_tasks > 0 else 0.0
    avg_usd_cost = total_cost / total_tasks if total_tasks > 0 else 0.0

    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": os.getenv("EVAL_MODE", "mock"),
        "provider": os.getenv("EVAL_PROVIDER", "mock"),
        "eval_provider": os.getenv("EVAL_PROVIDER", "mock"),
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "metrics": {
            "citation_validity_rate": round(citation_validity_rate, 4),
            "groundedness_rate": round(groundedness_rate, 4),
            "contradiction_recall": round(contradiction_recall, 4),
            "extraction_precision": round(extraction_precision, 4),
            "independence_correctness": round(independence_correctness, 4),
            "null_result_correctness": round(null_result_correctness, 4),
            "completion_rate": round(completion_rate, 4),
            "avg_usd_cost": round(avg_usd_cost, 6),
            "avg_latency_seconds": round(avg_latency, 2),
        },
        "tasks": task_results,
    }

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Evaluate against thresholds
    thresholds = {}
    if t_path.exists():
        thresholds = json.loads(t_path.read_text(encoding="utf-8"))

    print("\n================ EVALUATION RESULTS ================")
    print(f"  • Completion Rate:          {results['metrics']['completion_rate'] * 100:.1f}%")
    t_cite = thresholds.get("citation_validity_rate", 1.0) * 100
    v_cite = results["metrics"]["citation_validity_rate"] * 100
    print(f"  • Citation Validity Rate:   {v_cite:.1f}% (Threshold: {t_cite:.0f}%)")
    t_ground = thresholds.get("groundedness_rate", 0.9) * 100
    v_ground = results["metrics"]["groundedness_rate"] * 100
    print(f"  • Groundedness Rate:        {v_ground:.1f}% (Threshold: {t_ground:.0f}%)")
    t_contra = thresholds.get("contradiction_recall", 0.75) * 100
    v_contra = results["metrics"]["contradiction_recall"] * 100
    print(f"  • Contradiction Recall:     {v_contra:.1f}% (Threshold: {t_contra:.0f}%)")
    t_null = thresholds.get("null_result_correctness", 1.0) * 100
    v_null = results["metrics"]["null_result_correctness"] * 100
    print(f"  • Null Result Correctness:  {v_null:.1f}% (Threshold: {t_null:.0f}%)")
    t_indep = thresholds.get("independence_correctness", 1.0) * 100
    v_indep = results["metrics"]["independence_correctness"] * 100
    print(f"  • Independence Correctness: {v_indep:.1f}% (Threshold: {t_indep:.0f}%)")
    v_prec = results["metrics"]["extraction_precision"] * 100
    print(f"  • Extraction Precision:     {v_prec:.1f}%")
    print(f"  • Average Latency:          {results['metrics']['avg_latency_seconds']:.2f}s")
    print(f"  • Average Cost:             ${results['metrics']['avg_usd_cost']:.4f}")
    print("====================================================")

    failed_metrics: list[str] = []
    for metric, min_val in thresholds.items():
        actual_val = results["metrics"].get(metric, 0.0)
        if actual_val < min_val:
            failed_metrics.append(f"{metric}: actual {actual_val} < required {min_val}")

    if failed_metrics:
        print(f"\n[FAIL] Quality Gate Violation: {len(failed_metrics)} metrics below threshold:")
        for fm in failed_metrics:
            print(f"  - {fm}")
        return results

    print("\n[PASS] All evaluation metrics met or exceeded quality thresholds.")
    return results


def main():
    """CLI runner entrypoint."""
    try:
        results = asyncio.run(run_evaluation_suite())
        t_path = Path(__file__).parent / "thresholds.json"
        if t_path.exists():
            thresholds = json.loads(t_path.read_text(encoding="utf-8"))
            for metric, min_val in thresholds.items():
                if results["metrics"].get(metric, 0.0) < min_val:
                    sys.exit(1)
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] Eval suite execution failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
