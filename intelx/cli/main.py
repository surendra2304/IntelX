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


def run_seed_demo(_args: argparse.Namespace) -> None:
    """Seed local fixture documents and initialize a demo research investigation."""

    async def _async_seed():
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

    asyncio.run(_async_seed())


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
    }

    handler = command_handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
