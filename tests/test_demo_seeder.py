"""Tests for Demo Seeder, Canonical Demonstrations, and Sha256 Helpers."""

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select

from intelx.db.demo_seeder import _compute_sha256, auto_seed_demonstrations_if_empty
from intelx.db.models import Artifact, Claim, Finding, ResearchRun, Source
from intelx.db.repos import AuditChain
from intelx.db.session import get_sessionmaker


def test_compute_sha256_formats(tmp_path: Path):
    """Verify _compute_sha256 handles strings, bytes, and Path objects identically."""
    text_sample = "sodium-ion battery benchmarks 2026"
    expected_hex = hashlib.sha256(text_sample.encode("utf-8")).hexdigest()

    # 1. String input
    assert _compute_sha256(text_sample) == expected_hex

    # 2. Bytes input
    assert _compute_sha256(text_sample.encode("utf-8")) == expected_hex

    # 3. Path input
    file_path = tmp_path / "sample.txt"
    file_path.write_text(text_sample, encoding="utf-8")
    assert _compute_sha256(file_path) == expected_hex


@pytest.mark.asyncio
async def test_auto_seed_demonstrations_lifecycle():
    """Verify seeding creates canonical runs, claims, artifacts, and passes audit verification."""
    sessionmaker = get_sessionmaker()

    # 1. First execution should seed successfully and return True
    async with sessionmaker() as session:
        seeded = await auto_seed_demonstrations_if_empty(session)
        assert seeded is True

    # 2. Verify all 4 canonical demonstration runs and their entities exist
    async with sessionmaker() as session:
        canonical_ids = [
            "run-na-battery-001",
            "run-solid-state-002",
            "run-multiagent-003",
            "run-quantum-004",
        ]
        runs = (
            (await session.execute(select(ResearchRun).where(ResearchRun.id.in_(canonical_ids))))
            .scalars()
            .all()
        )
        assert len(runs) == 4

        run_ids = {r.id for r in runs}
        assert "run-na-battery-001" in run_ids
        assert "run-solid-state-002" in run_ids
        assert "run-multiagent-003" in run_ids
        assert "run-quantum-004" in run_ids

        # Verify sources, claims, findings, artifacts
        sources = (await session.execute(select(Source))).scalars().all()
        assert len(sources) == 9

        claims = (await session.execute(select(Claim))).scalars().all()
        assert len(claims) == 9

        findings = (await session.execute(select(Finding))).scalars().all()
        assert len(findings) == 5

        artifacts = (await session.execute(select(Artifact))).scalars().all()
        assert len(artifacts) >= 8

        # Verify cryptographic audit chain integrity
        is_valid, errors = await AuditChain.verify(session)
        assert is_valid is True
        assert len(errors) == 0

        # 3. Second execution should be idempotent and return False without modifying
        second_seed = await auto_seed_demonstrations_if_empty(session)
        assert second_seed is False
