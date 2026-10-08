"""Regression coverage for robust golden-evaluation evidence lookups."""

from types import SimpleNamespace

import pytest

from evals.run import _has_traceable_conflict_pair, evaluation_db_url
from intelx.core.enums import ClaimStatus


class DuplicateResult:
    """Small result double exposing duplicate rows without strict-one semantics."""

    def __init__(self, rows):
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None


class DuplicateEvidenceSession:
    async def execute(self, _statement):
        return DuplicateResult([("evidence-1",), ("evidence-duplicate",)])


def test_eval_database_isolated_from_development_database(monkeypatch):
    """Golden evaluation must not share the running app's SQLite database."""
    monkeypatch.delenv("INTELX_EVAL_DB_URL", raising=False)
    assert evaluation_db_url().endswith("/data/eval.db")
    monkeypatch.setenv("INTELX_EVAL_DB_URL", "sqlite+aiosqlite:///custom-eval.db")
    assert evaluation_db_url() == "sqlite+aiosqlite:///custom-eval.db"


@pytest.mark.asyncio
async def test_conflict_gate_accepts_existential_matches_with_duplicate_evidence():
    claims = [
        SimpleNamespace(
            id="claim-420",
            source_id="source-a",
            document_id="doc-a",
            chunk_id="chunk-a",
            span_start=0,
            span_end=10,
            quote="Reported 420 Wh/kg for silicon composite anode.",
            status=ClaimStatus.DISPUTED,
        ),
        SimpleNamespace(
            id="claim-310",
            source_id="source-b",
            document_id="doc-b",
            chunk_id="chunk-b",
            span_start=0,
            span_end=10,
            quote="Reported 310 Wh/kg limit for silicon composite anode.",
            status=ClaimStatus.DISPUTED,
        ),
    ]

    assert await _has_traceable_conflict_pair(
        DuplicateEvidenceSession(),
        "run-1",
        claims,
        ["420 Wh/kg", "310 Wh/kg"],
    )
