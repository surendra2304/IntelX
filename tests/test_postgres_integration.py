"""Tests for Production PostgreSQL Integration, pooling, and repository dialect handling."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import ClaimType, EvidenceSupportType
from intelx.core.errors import IntegrityError
from intelx.core.settings import Settings
from intelx.db import engine as db_engine
from intelx.db.repos import ClaimRepo, EvidenceRepo, RunRepo, SourceRepo
from intelx.db.session import get_sessionmaker


def test_postgres_url_normalization():
    """Verify various postgres URL formats normalize cleanly to asyncpg."""
    s1 = Settings(
        _env_file=None, POSTGRES_URL="postgres://user:pass@dokploy-postgres:5432/intelx_db"
    )
    assert s1.DB_URL == "postgresql+asyncpg://user:pass@dokploy-postgres:5432/intelx_db"

    s2 = Settings(
        _env_file=None, POSTGRESQL_URL="postgresql://user:pass@dokploy-postgres:5432/intelx_db"
    )
    assert s2.DB_URL == "postgresql+asyncpg://user:pass@dokploy-postgres:5432/intelx_db"

    s3 = Settings(
        _env_file=None, INTELX_POSTGRES_URL="postgresql+psycopg2://user:pass@localhost:5432/db"
    )
    assert s3.DB_URL == "postgresql+asyncpg://user:pass@localhost:5432/db"


def test_postgres_engine_pool_parameters(monkeypatch):
    """Verify get_async_engine configures production connection pool for postgres."""
    captured_kwargs = {}

    def mock_create_async_engine(url, **kwargs):
        captured_kwargs.update(kwargs)
        mock_eng = MagicMock()
        mock_eng.dialect.name = "postgresql"
        return mock_eng

    monkeypatch.setattr(db_engine, "create_async_engine", mock_create_async_engine)
    monkeypatch.setattr(db_engine, "_engine", None)

    pg_url = "postgresql+asyncpg://intelx_user:secret@dokploy-postgres:5432/intelx_db"
    eng = db_engine.get_async_engine(pg_url)
    assert eng is not None
    assert captured_kwargs.get("pool_size") == 10
    assert captured_kwargs.get("max_overflow") == 20
    assert captured_kwargs.get("pool_recycle") == 300
    assert captured_kwargs.get("pool_pre_ping") is True

    # Reset engine
    db_engine._engine = None


@pytest.mark.asyncio
async def test_search_claims_fts_dialect_awareness():
    """Verify search_claims_fts directly uses ILIKE on PostgreSQL and does not invoke SQLite MATCH."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    mock_session.get_bind.return_value = mock_bind

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    claims = await ClaimRepo.search_claims_fts(mock_session, "quantum computing")
    assert isinstance(claims, list)

    # In postgres, only select(Claim)...ilike is executed (1 call), raw SQL with MATCH is never called
    assert mock_session.execute.call_count == 1
    call_args = mock_session.execute.call_args[0][0]
    assert "like" in str(call_args).lower()


@pytest.mark.asyncio
async def test_evidence_strict_span_integrity_validation():
    """Verify Safety Invariant 2: evidence requires exact verbatim character slice match."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        # Create Run, Source, Document, Chunk
        run = await RunRepo.create_run(session, objective="Test evidence span validation")
        src = await SourceRepo.create_source(
            session=session,
            location="https://test.example/doc1",
            kind="web",
            title="Evidence Test Document",
        )
        full_text = "The breakthrough yielded 99.8% purity at room temperature under 1 atm."
        doc = await SourceRepo.create_document(
            session=session, source_id=src.id, text_content=full_text
        )
        chunk = await SourceRepo.create_chunk(
            session=session,
            document_id=doc.id,
            idx=0,
            start_char=0,
            end_char=len(full_text),
            text_content=full_text,
        )

        # Verbatim quote matches slice
        quote = "99.8% purity"
        start = full_text.index(quote)
        end = start + len(quote)

        claim = await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=src.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            text_content="The material achieved 99.8% purity.",
            claim_type=ClaimType.MEASUREMENT,
            quote=quote,
            span_start=start,
            span_end=end,
            created_by_agent="test-agent",
        )
        assert claim.id is not None

        # Creating evidence with correct span succeeds
        ev = await EvidenceRepo.create_evidence(
            session=session,
            claim_id=claim.id,
            source_id=src.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            span_start=start,
            span_end=end,
            quote=quote,
            support_type=EvidenceSupportType.SUPPORTS,
            created_by_run_id=run.id,
            created_by_agent="test-agent",
        )
        assert ev.id is not None
        assert ev.quote == quote

        # Creating evidence with mismatched quote raises IntegrityError
        with pytest.raises(IntegrityError, match="Evidence span verification failed"):
            await EvidenceRepo.create_evidence(
                session=session,
                claim_id=claim.id,
                source_id=src.id,
                document_id=doc.id,
                chunk_id=chunk.id,
                span_start=start,
                span_end=end,
                quote="hallucinated quote",
                support_type=EvidenceSupportType.SUPPORTS,
                created_by_run_id=run.id,
                created_by_agent="test-agent",
            )
