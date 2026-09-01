"""Tests for INTELX Command Line Interface (CLI) parsers and command dispatch."""

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

from intelx.cli.main import (
    build_parser,
    run_purge,
    run_verify_audit,
)


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
    args_smoke_live = parser.parse_args([
        "smoke-live",
        "--objective", "Test query",
        "--max-sources", "8",
        "--max-usd", "2.0",
    ])
    assert args_smoke_live.command == "smoke-live"
    assert args_smoke_live.objective == "Test query"
    assert args_smoke_live.max_sources == 8
    assert args_smoke_live.max_usd == 2.0


def test_cli_verify_audit_command():
    """Verify audit verification CLI output when audit chain is valid."""
    def _fake_run(coro):
        coro.close()
        return None

    with patch("asyncio.run", side_effect=_fake_run) as mock_asyncio_run:
        args = argparse.Namespace(command="verify-audit")
        run_verify_audit(args)
        assert mock_asyncio_run.called


def test_cli_purge_command():
    """Verify purge CLI command execution."""
    def _fake_run(coro):
        coro.close()
        return None

    with patch("asyncio.run", side_effect=_fake_run) as mock_asyncio_run:
        args = argparse.Namespace(command="purge", days=30)
        run_purge(args)
        assert mock_asyncio_run.called
