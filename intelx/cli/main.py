"""INTELX Unified Command Line Interface (CLI)."""

import argparse
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

from intelx.core.logging import setup_logging
from intelx.core.settings import get_settings


def run_serve(args: argparse.Namespace) -> None:
    """Launch the FastAPI application server via Uvicorn."""
    import uvicorn

    setup_logging()
    host = args.host or "0.0.0.0"
    port = args.port or 8000
    print(f"[INTELX] Starting server on http://{host}:{port}")
    uvicorn.run(
        "intelx.app.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )


def run_worker(_args: argparse.Namespace) -> None:
    """Launch the background orchestration worker loop."""
    from intelx.orchestration.worker import OrchestrationWorker

    setup_logging()
    print("[INTELX] Starting background orchestration worker daemon...")
    worker = OrchestrationWorker()
    try:
        asyncio.run(worker.start())
    except KeyboardInterrupt:
        worker.stop()
        print("\n[INTELX] Worker shutdown gracefully.")


def run_migrate(_args: argparse.Namespace) -> None:
    """Execute Alembic database migrations."""
    print("[INTELX] Applying database migrations...")
    res = subprocess.run(["alembic", "upgrade", "head"])
    sys.exit(res.returncode)


async def seed_demo_async() -> str:
    """Seed local fixture documents and initialize a demo research investigation asynchronously."""
    from intelx.db.base import Base
    from intelx.db.engine import get_async_engine
    from intelx.db.repos import RunRepo
    from intelx.db.session import get_sessionmaker

    settings = get_settings()
    uploads_dir = Path(settings.DATA_DIR) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    fixtures_dir = Path(__file__).resolve().parent.parent.parent / "evals" / "fixtures"
    if fixtures_dir.exists():
        copied_count = 0
        for fix_file in fixtures_dir.glob("*.txt"):
            dest = uploads_dir / fix_file.name
            shutil.copy2(fix_file, dest)
            copied_count += 1
        print(f"[INTELX] Copied {copied_count} fixture documents to {uploads_dir}")

    # Ensure database tables exist
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        demo_obj = (
            "Assess next-generation layered oxide sodium-ion cathode benchmarks, "
            "energy density limits, and thermal runaway thresholds"
        )
        run = await RunRepo.create_run(
            session=session,
            objective=demo_obj,
            scope_json={
                "depth": "standard",
                "max_sources": 10,
                "budget": {"max_usd": 5.0, "max_minutes": 15},
            },
            created_by="intelx-cli-demo",
        )
        await session.commit()
        print(f"[INTELX] Created Demo Research Run: {run.id}")
        print(f"  Objective: '{demo_obj}'")
        print("  Status:    QUEUED (Ready for execution)")
        print("\nRun 'intelx worker' or 'make dev' to start automated processing.")
        return run.id


def run_seed_demo(_args: argparse.Namespace) -> None:
    """Seed local fixture documents and initialize a demo research investigation."""
    asyncio.run(seed_demo_async())


def run_eval(_args: argparse.Namespace) -> None:
    """Execute the deterministic golden evaluation benchmark suite."""
    from evals.run import main as eval_main

    eval_main()


def run_purge(args: argparse.Namespace) -> None:
    """Execute raw cache retention purge."""
    from intelx.core.retention import execute_retention_purge

    days = args.days if args.days is not None else 30
    asyncio.run(execute_retention_purge(older_than_days=days))


def run_verify_audit(_args: argparse.Namespace) -> None:
    """Cryptographically verify the integrity of the audit event ledger."""

    async def _async_verify():
        from intelx.db.repos import AuditChain
        from intelx.db.session import get_sessionmaker

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            is_valid, errors = await AuditChain.verify(session)
            print("\n================ AUDIT CHAIN INTEGRITY ================")
            print(f"  • Ledger Integrity:      {'VALID' if is_valid else 'COMPROMISED'}")
            print(f"  • Tamper Violations:     {len(errors)}")
            if errors:
                for err in errors:
                    print(f"    - {err}")
            else:
                print("  • Verification Status:   All audit events cryptographically valid.")
            print("========================================================")
            if not is_valid:
                sys.exit(1)

    asyncio.run(_async_verify())


def run_smoke_llm(_args: argparse.Namespace) -> None:
    """Smoke test live LLM providers across all agent roles."""
    settings = get_settings()
    if settings.MOCK_MODE:
        print("mock mode — nothing to smoke")
        sys.exit(0)

    async def _async_smoke():
        import time

        from pydantic import BaseModel, Field

        from intelx.models.gateway import ModelGateway

        class SmokeTestSchema(BaseModel):
            status: str = Field(description="Operational status (e.g. OK)")
            role: str = Field(description="Agent role tested")
            notes: str = Field(default="")

        gateway = ModelGateway(settings=settings)
        roles = ["planner", "extractor", "verifier", "analyst", "synthesizer", "critic"]

        print("\n================ INTELX LLM GATEWAY SMOKE ================")
        print(f"Provider: {settings.LLM_PROVIDER} | Default Model: {settings.LLM_MODEL}")
        print(
            f"{'Role':<14} | {'Model':<20} | {'Status':<8} | {'Lat (s)':<8} | {'Tokens (In/Out)':<16} | {'USD Cost':<10}"
        )
        print("-" * 86)

        failures = []
        total_cost = 0.0

        for r in roles:
            m_name = settings.get_model_for_role(r)
            start_t = time.time()
            try:
                test_messages = [
                    {
                        "role": "system",
                        "content": f"You are the INTELX {r.capitalize()} agent. Respond with valid JSON.",
                    },
                    {
                        "role": "user",
                        "content": f"Execute diagnostic self-check for role '{r}'. Return status OK.",
                    },
                ]
                res = await gateway.complete(
                    messages=test_messages,
                    role=r,
                    schema_model=SmokeTestSchema,
                )
                dur = time.time() - start_t
                u = res.usage
                total_cost += u.usd_cost
                tokens_str = f"{u.input_tokens}/{u.output_tokens}"
                print(
                    f"{r:<14} | {m_name:<20} | {'OK':<8} | {dur:<8.2f} | {tokens_str:<16} | ${u.usd_cost:<9.6f}"
                )
            except Exception as e:
                dur = time.time() - start_t
                print(
                    f"{r:<14} | {m_name:<20} | {'FAILED':<8} | {dur:<8.2f} | {'N/A':<16} | ${0.0:<9.6f}"
                )
                failures.append((r, str(e)))

        print("-" * 86)
        print(f"Total Diagnostic Cost: ${total_cost:.6f}")
        if failures:
            print(f"\n[FAIL] {len(failures)} LLM role checks failed:")
            for role_fail, err_msg in failures:
                print(f"  - [{role_fail}]: {err_msg}")
            sys.exit(1)
        else:
            print("\n[PASS] All agent role gateway endpoints operational.")

    asyncio.run(_async_smoke())


def run_smoke_live(args: argparse.Namespace) -> None:
    """Execute one complete live research investigation through real search and LLM providers."""
    settings = get_settings()
    if settings.MOCK_MODE:
        print(
            "[ERROR] Cannot run smoke-live with MOCK_MODE=True. Set INTELX_MOCK_MODE=false and provide live API keys."
        )
        sys.exit(1)

    if not settings.LLM_API_KEY:
        print(
            "[ERROR] Missing LLM API key. Set INTELX_LLM_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY."
        )
        sys.exit(1)

    if not settings.TAVILY_API_KEY:
        print("[ERROR] Missing search API key. Set INTELX_TAVILY_API_KEY or TAVILY_API_KEY.")
        sys.exit(1)

    async def _async_live_run():
        import json
        import re
        import time

        from sqlalchemy import select

        from intelx.core.enums import ArtifactFormat, ClaimStatus
        from intelx.core.report import validate_citations
        from intelx.db.base import Base
        from intelx.db.engine import get_async_engine
        from intelx.db.models import Artifact, Claim, Source
        from intelx.db.repos import RunRepo
        from intelx.db.session import get_sessionmaker
        from intelx.orchestration.engine import OrchestrationEngine

        objective = (
            args.objective
            or "Assess sodium-ion cathode benchmarks, energy density limits, and thermal runaway thresholds"
        )
        max_sources = args.max_sources if args.max_sources is not None else 5
        max_usd = args.max_usd if args.max_usd is not None else 1.50

        print("\n================ INTELX LIVE RESEARCH RUN ================")
        print(f"Objective:   '{objective}'")
        print(f"Max Sources: {max_sources} | Max Budget: ${max_usd:.2f}")
        print(f"Provider:    {settings.LLM_PROVIDER} | Search: Tavily")
        print("----------------------------------------------------------")

        # 1. Initialize schema and run
        engine_db = get_async_engine()
        async with engine_db.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            run = await RunRepo.create_run(
                session=session,
                objective=objective,
                scope_json={
                    "depth": "standard",
                    "max_sources": max_sources,
                    "budget": {"max_usd": max_usd, "max_minutes": 10},
                },
                created_by="intelx-smoke-live",
            )
            await session.commit()
            run_id = run.id

        print(f"[INTELX] Created live research job: {run_id}")
        print("[INTELX] Executing orchestration DAG in-process...")

        start_time = time.time()
        engine = OrchestrationEngine(settings=settings)
        async with sessionmaker() as session:
            final_run = await engine.execute_run(session=session, run_id=run_id)
            duration = time.time() - start_time

            claims = list(
                (await session.execute(select(Claim).where(Claim.run_id == run_id))).scalars().all()
            )
            sources = list(
                (await session.execute(select(Source).where(Source.created_by_run_id == run_id)))
                .scalars()
                .all()
            )
            all_sources = list((await session.execute(select(Source))).scalars().all())

            active_claims = [c for c in claims if c.status == ClaimStatus.ACTIVE]
            disputed_claims = [c for c in claims if c.status == ClaimStatus.DISPUTED]

            snippet_sources = [
                s
                for s in sources
                if s.license_note == "search-engine-snippet" or "(Snippet)" in (s.title or "")
            ]
            full_sources = [s for s in sources if s not in snippet_sources]

            art_stmt = select(Artifact).where(
                Artifact.run_id == run_id, Artifact.format == ArtifactFormat.MD
            )
            art = (await session.execute(art_stmt)).scalars().first()
            md_content = (
                Path(art.path).read_text(encoding="utf-8")
                if (art and Path(art.path).exists())
                else ""
            )

            tokens = re.findall(r"\[[SC]:[a-zA-Z0-9_\-]+\]", md_content)
            valid_src_ids = {s.id for s in all_sources}
            valid_cl_ids = {c.id for c in claims}
            try:
                validate_citations(md_content, valid_src_ids, valid_cl_ids)
                citation_verdict = "VALID (100% resolved)"
            except Exception as e:
                citation_verdict = f"INVALID: {e}"

            alignment_rate = 1.0
            for ev in final_run.events:
                if ev.type == "claim.alignment_stats" and ev.payload_json:
                    alignment_rate = ev.payload_json.get("span_alignment_rate", 1.0)

            print("\n================ LIVE RUN EXECUTION SUMMARY ================")
            print(
                f"Status / Outcome:      {final_run.status.value} / {final_run.outcome.value if final_run.outcome else 'N/A'}"
            )
            print(f"Execution Duration:    {duration:.2f}s")
            print(f"Total USD Cost:        ${final_run.usd_cost:.6f} (Budget: ${max_usd:.2f})")
            print(
                f"Sources Ingested:      {len(sources)} total ({len(full_sources)} full-text, {len(snippet_sources)} search snippet)"
            )
            print(
                f"Claims Extracted:      {len(claims)} total ({len(active_claims)} ACTIVE, {len(disputed_claims)} DISPUTED)"
            )
            print(f"Span Alignment Rate:   {alignment_rate * 100:.1f}%")
            print(f"Report Citations:      {len(tokens)} tokens — {citation_verdict}")

            lines = md_content.splitlines()
            direct_answer_lines = []
            in_answer = False
            for line in lines:
                if line.startswith("## Direct Answer"):
                    in_answer = True
                    continue
                elif in_answer and line.startswith("## "):
                    break
                elif in_answer and line.strip():
                    direct_answer_lines.append(line.strip())
                    if len(direct_answer_lines) >= 5:
                        break

            print("\n--- Direct Answer Sample (first 5 lines) ---")
            for al in direct_answer_lines:
                print(al)
            print("---------------------------------------------")

            live_results = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "mode": "live",
                "provider": settings.LLM_PROVIDER,
                "model": settings.LLM_MODEL,
                "objective": objective,
                "status": final_run.status.value,
                "outcome": final_run.outcome.value if final_run.outcome else None,
                "duration_seconds": round(duration, 2),
                "usd_cost": round(final_run.usd_cost, 6),
                "sources_count": len(sources),
                "full_sources_count": len(full_sources),
                "snippet_sources_count": len(snippet_sources),
                "claims_count": len(claims),
                "active_claims_count": len(active_claims),
                "disputed_claims_count": len(disputed_claims),
                "span_alignment_rate": round(alignment_rate, 4),
                "citation_tokens_count": len(tokens),
                "citation_verdict": citation_verdict,
            }
            out_path = Path("evals/results-live.json")
            out_path.write_text(json.dumps(live_results, indent=2), encoding="utf-8")
            print(f"\n[INTELX] Live execution metrics saved to {out_path}")

    asyncio.run(_async_live_run())


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser and command routes."""
    parser = argparse.ArgumentParser(
        prog="intelx",
        description="INTELX: Evidence-Driven Intelligence Research Monolith",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start the FastAPI application server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host address")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port number")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    # worker
    subparsers.add_parser("worker", help="Start the background orchestration worker")

    # migrate
    subparsers.add_parser("migrate", help="Run database migrations (Alembic)")

    # seed-demo
    subparsers.add_parser("seed-demo", help="Seed fixtures and queue a demo research run")

    # eval
    subparsers.add_parser("eval", help="Run the golden evaluation benchmark suite")

    # purge
    purge_parser = subparsers.add_parser("purge", help="Purge stale raw cache files")
    purge_parser.add_argument("--days", type=int, default=30, help="Retention threshold in days")

    # verify-audit
    subparsers.add_parser("verify-audit", help="Verify cryptographic audit chain integrity")

    # smoke-llm
    subparsers.add_parser("smoke-llm", help="Smoke test live LLM providers across all roles")

    # smoke-live
    live_parser = subparsers.add_parser(
        "smoke-live", help="Execute one complete live research run against real providers"
    )
    live_parser.add_argument("--objective", type=str, default=None, help="Research objective")
    live_parser.add_argument(
        "--max-sources", type=int, default=5, help="Max source documents to retrieve"
    )
    live_parser.add_argument(
        "--max-usd", type=float, default=1.50, help="Max USD budget cap for the run"
    )

    return parser


def main() -> None:
    """CLI application entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    command_handlers = {
        "serve": run_serve,
        "worker": run_worker,
        "migrate": run_migrate,
        "seed-demo": run_seed_demo,
        "eval": run_eval,
        "purge": run_purge,
        "verify-audit": run_verify_audit,
        "smoke-llm": run_smoke_llm,
        "smoke-live": run_smoke_live,
    }

    handler = command_handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
