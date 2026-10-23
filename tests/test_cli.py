"""Tests for INTELX Command Line Interface (CLI) parsers and command dispatch."""

import argparse
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from intelx.cli.main import (
    build_parser,
    main,
    run_eval,
    run_migrate,
    run_purge,
    run_seed_demo,
    run_serve,
    run_smoke_live,
    run_smoke_llm,
    run_verify_audit,
    run_worker,
    seed_demo_async,
)
from intelx.core.settings import Settings
from intelx.db.models import ResearchRun
from intelx.db.session import get_sessionmaker


def test_cli_parser_subcommands():
    """Verify all 9 subcommands are configured with expected flags."""
    parser = build_parser()

    # 1. serve
    args_serve = parser.parse_args(["serve", "--port", "8080", "--host", "127.0.0.1", "--reload"])
    assert args_serve.command == "serve"
    assert args_serve.port == 8080
    assert args_serve.host == "127.0.0.1"
    assert args_serve.reload is True

    # 2. worker
    args_worker = parser.parse_args(["worker"])
    assert args_worker.command == "worker"

    # 3. migrate
    args_migrate = parser.parse_args(["migrate"])
    assert args_migrate.command == "migrate"

    # 4. seed-demo
    args_seed = parser.parse_args(["seed-demo"])
    assert args_seed.command == "seed-demo"

    # 5. eval
    args_eval = parser.parse_args(["eval"])
    assert args_eval.command == "eval"

    # 6. purge
    args_purge = parser.parse_args(["purge", "--days", "45"])
    assert args_purge.command == "purge"
    assert args_purge.days == 45

    # 7. verify-audit
    args_audit = parser.parse_args(["verify-audit"])
    assert args_audit.command == "verify-audit"

    # 8. smoke-llm
    args_smoke_llm = parser.parse_args(["smoke-llm"])
    assert args_smoke_llm.command == "smoke-llm"

    # 9. smoke-live
    args_smoke_live = parser.parse_args(
        [
            "smoke-live",
            "--objective",
            "Test query",
            "--max-sources",
            "8",
            "--max-usd",
            "2.0",
        ]
    )
    assert args_smoke_live.command == "smoke-live"
    assert args_smoke_live.objective == "Test query"
    assert args_smoke_live.max_sources == 8
    assert args_smoke_live.max_usd == 2.0


def test_serve_uses_platform_port_environment(monkeypatch):
    """Verify serve defaults to PORT env variable."""
    monkeypatch.setenv("PORT", "9123")
    args = build_parser().parse_args(["serve"])

    with patch("uvicorn.run") as mock_run:
        run_serve(args)

    assert mock_run.call_args.kwargs["port"] == 9123
    assert mock_run.call_args.kwargs["host"] == "0.0.0.0"


def test_run_worker_clean_and_keyboard_interrupt():
    """Verify worker execution and graceful KeyboardInterrupt shutdown."""
    mock_worker = MagicMock()
    mock_worker.start = AsyncMock()
    mock_worker.stop = MagicMock()

    args = argparse.Namespace(command="worker")
    with patch("intelx.orchestration.worker.OrchestrationWorker", return_value=mock_worker):
        # 1. Clean worker execution
        with patch("asyncio.run") as mock_run:
            run_worker(args)
            assert mock_run.called

        # 2. KeyboardInterrupt handling
        with patch("asyncio.run", side_effect=KeyboardInterrupt):
            run_worker(args)
            mock_worker.stop.assert_called_once()


def test_run_migrate():
    """Verify database migration dispatch and exit code propagation."""
    args = argparse.Namespace(command="migrate")
    res_mock = subprocess.CompletedProcess(args=["alembic", "upgrade", "head"], returncode=0)

    with (
        patch("subprocess.run", return_value=res_mock) as mock_sub,
        pytest.raises(SystemExit) as exc_info,
    ):
        run_migrate(args)

    assert exc_info.value.code == 0
    mock_sub.assert_called_once_with(["alembic", "upgrade", "head"])


@pytest.mark.asyncio
async def test_seed_demo_async_and_run_seed_demo():
    """Verify demo research investigation generation via CLI."""
    run_id = await seed_demo_async()
    assert run_id is not None

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        run = (
            await session.execute(select(ResearchRun).where(ResearchRun.id == run_id))
        ).scalar_one_or_none()
        assert run is not None
        assert run.created_by == "intelx-cli-demo"
        assert "sodium-ion" in run.objective

    # Test sync wrapper
    with patch("asyncio.run") as mock_run:
        run_seed_demo(argparse.Namespace())
        assert mock_run.called


def test_run_eval():
    """Verify eval benchmark invocation."""
    with patch("evals.run.main") as mock_eval_main:
        run_eval(argparse.Namespace())
        mock_eval_main.assert_called_once()


def test_run_purge_execution():
    """Verify retention purge dispatch with days argument."""
    with patch("asyncio.run") as mock_run:
        run_purge(argparse.Namespace(days=14))
        assert mock_run.called


def test_run_verify_audit_pass_and_fail():
    """Verify cryptographic audit chain verification in both valid and tampered states."""
    args = argparse.Namespace(command="verify-audit")

    # 1. Valid state
    with patch(
        "intelx.db.repos.AuditChain.verify", new_callable=AsyncMock, return_value=(True, [])
    ):
        run_verify_audit(args)

    # 2. Tampered state -> raises SystemExit(1)
    with (
        patch(
            "intelx.db.repos.AuditChain.verify",
            new_callable=AsyncMock,
            return_value=(False, ["Hash mismatch on block 4"]),
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        run_verify_audit(args)

    assert exc_info.value.code == 1


def test_run_smoke_llm():
    """Verify smoke-llm in mock mode and live mode."""
    # 1. In mock mode -> exits 0 cleanly
    mock_settings = Settings(MOCK_MODE=True)
    with (
        patch("intelx.cli.main.get_settings", return_value=mock_settings),
        pytest.raises(SystemExit) as exc_info,
    ):
        run_smoke_llm(argparse.Namespace())
    assert exc_info.value.code == 0

    # 2. In live mode with mocked completions
    live_settings = Settings(
        MOCK_MODE=False,
        LLM_PROVIDER="openai_compatible",
        OPENAI_API_KEY="test-openai-key",
    )
    mock_completion = MagicMock()
    mock_completion.usage.usd_cost = 0.0001
    mock_completion.usage.input_tokens = 50
    mock_completion.usage.output_tokens = 20

    with (
        patch("intelx.cli.main.get_settings", return_value=live_settings),
        patch(
            "intelx.models.gateway.ModelGateway.complete",
            new_callable=AsyncMock,
            return_value=mock_completion,
        ),
    ):
        run_smoke_llm(argparse.Namespace())

    # 3. In live mode with gateway failures -> exits 1
    with (
        patch("intelx.cli.main.get_settings", return_value=live_settings),
        patch(
            "intelx.models.gateway.ModelGateway.complete",
            side_effect=RuntimeError("Provider connection error"),
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        run_smoke_llm(argparse.Namespace())
    assert exc_info.value.code == 1


def test_run_smoke_live_credential_checks():
    """Verify smoke-live rejects invalid or missing credentials."""
    args = argparse.Namespace(objective=None, max_sources=None, max_usd=None)

    # 1. Mock mode active -> exits 1
    with (
        patch("intelx.cli.main.get_settings", return_value=Settings(MOCK_MODE=True)),
        pytest.raises(SystemExit) as exc_info,
    ):
        run_smoke_live(args)
    assert exc_info.value.code == 1

    # 2. Unsupported provider -> exits 1
    mock_unsupported = MagicMock()
    mock_unsupported.MOCK_MODE = False
    mock_unsupported.LLM_PROVIDER = "unsupported_custom"
    with (
        patch("intelx.cli.main.get_settings", return_value=mock_unsupported),
        pytest.raises(SystemExit) as exc_info,
    ):
        run_smoke_live(args)
    assert exc_info.value.code == 1

    # 3. Missing search key -> exits 1
    mock_missing_search = MagicMock()
    mock_missing_search.MOCK_MODE = False
    mock_missing_search.LLM_PROVIDER = "inference"
    mock_missing_search.INFERENCE_API_KEY = "test-key"
    mock_missing_search.TAVILY_API_KEY = ""
    with (
        patch("intelx.cli.main.get_settings", return_value=mock_missing_search),
        pytest.raises(SystemExit) as exc_info,
    ):
        run_smoke_live(args)
    assert exc_info.value.code == 1

    # 4. Anthropic missing key -> exits 1
    mock_anthropic = MagicMock()
    mock_anthropic.MOCK_MODE = False
    mock_anthropic.LLM_PROVIDER = "anthropic"
    mock_anthropic.get_llm_api_key.return_value = ""
    with (
        patch("intelx.cli.main.get_settings", return_value=mock_anthropic),
        pytest.raises(SystemExit) as exc_info,
    ):
        run_smoke_live(args)
    assert exc_info.value.code == 1

    # 5. OpenAI compatible missing key -> exits 1
    mock_openai = MagicMock()
    mock_openai.MOCK_MODE = False
    mock_openai.LLM_PROVIDER = "openai_compatible"
    mock_openai.get_llm_api_key.return_value = ""
    with (
        patch("intelx.cli.main.get_settings", return_value=mock_openai),
        pytest.raises(SystemExit) as exc_info,
    ):
        run_smoke_live(args)
    assert exc_info.value.code == 1


def test_run_smoke_live_execution():
    """Verify smoke-live runs orchestration DAG and saves results."""
    from intelx.core.enums import RunOutcome, RunStatus

    mock_live_settings = Settings(
        MOCK_MODE=False,
        LLM_PROVIDER="inference",
        INFERENCE_API_KEY="test-inference-key",
        TAVILY_API_KEY="test-tavily-key",
    )
    mock_final_run = MagicMock()
    mock_final_run.status = RunStatus.COMPLETED
    mock_final_run.outcome = RunOutcome.ANSWERED
    mock_final_run.usd_cost = 0.0042
    mock_final_run.events = []

    args = argparse.Namespace(
        objective="Assess sodium-ion cathode benchmarks",
        max_sources=2,
        max_usd=0.50,
    )

    with (
        patch("intelx.cli.main.get_settings", return_value=mock_live_settings),
        patch(
            "intelx.orchestration.engine.OrchestrationEngine.execute_run",
            new_callable=AsyncMock,
            return_value=mock_final_run,
        ),
        patch("pathlib.Path.write_text") as mock_write,
    ):
        run_smoke_live(args)
        assert mock_write.called


def test_run_oracle_smoke():
    """Verify oracle-smoke runs connection ping and schema inspection."""
    from intelx.cli.main import run_oracle_smoke

    args = argparse.Namespace(db_url="sqlite+aiosqlite:///:memory:", create_tables=True)
    run_oracle_smoke(args)


def test_main_dispatch():
    """Verify main() parses argv and dispatches to appropriate handlers."""
    with (
        patch.object(sys, "argv", ["intelx", "purge", "--days", "7"]),
        patch("intelx.cli.main.run_purge") as mock_purge,
    ):
        main()
        mock_purge.assert_called_once()

    with (
        patch.object(sys, "argv", ["intelx", "oracle-smoke", "--create-tables"]),
        patch("intelx.cli.main.run_oracle_smoke") as mock_oracle_smoke,
    ):
        main()
        mock_oracle_smoke.assert_called_once()

    # Empty command prints help
    with (
        patch.object(sys, "argv", ["intelx"]),
        patch("argparse.ArgumentParser.print_help") as mock_help,
    ):
        main()
        mock_help.assert_called_once()
