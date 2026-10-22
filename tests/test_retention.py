from datetime import UTC, datetime, timedelta

import pytest

from intelx.core.enums import RunStatus, SourceKind
from intelx.db.repos import RunRepo, SourceRepo
from intelx.db.retention import purge_expired_retention
from intelx.db.session import get_sessionmaker


@pytest.mark.asyncio
async def test_retention_purge_raw_documents_and_expired_runs():
    """Verify raw document text is scrubbed after threshold and old runs are completely purged."""
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        # 1. Create a recent run (active, should NOT be touched)
        recent_run = await RunRepo.create_run(
            session=session,
            objective="Recent active investigation",
        )
        recent_run.status = RunStatus.COMPLETED

        # 2. Create an older run (older than 30 days, raw docs should be cleared)
        old_raw_run = await RunRepo.create_run(
            session=session,
            objective="Investigation from 45 days ago",
        )
        old_raw_run.status = RunStatus.COMPLETED
        old_raw_run.created_at = datetime.now(UTC) - timedelta(days=45)

        # Attach a document to old_raw_run
        source = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.FILE,
            location="file://data/test_old.txt",
            title="Old Source Document",
            created_by_run_id=old_raw_run.id,
        )
        doc = await SourceRepo.create_document(
            session=session,
            source_id=source.id,
            text_content="Original sensitive raw text from 45 days ago that should be purged.",
        )

        # 3. Create an ancient run (older than 365 days, full run should be deleted)
        ancient_run = await RunRepo.create_run(
            session=session,
            objective="Ancient investigation from 400 days ago",
        )
        ancient_run.status = RunStatus.COMPLETED
        ancient_run.created_at = datetime.now(UTC) - timedelta(days=400)
        ancient_id = ancient_run.id

        await session.commit()

        # Execute purge with 30-day raw docs and 365-day reports policy
        stats = await purge_expired_retention(
            session=session,
            raw_docs_retention_days=30,
            reports_retention_days=365,
        )

        assert stats["purged_runs_count"] >= 1
        assert stats["purged_raw_docs_count"] >= 1

        # Ancient run should be gone
        deleted_check = await RunRepo.get_run(session, ancient_id)
        assert deleted_check is None

        # Old raw run still exists, but document text is purged
        old_run_check = await RunRepo.get_run(session, old_raw_run.id)
        assert old_run_check is not None
        doc_check = await SourceRepo.get_document(session, doc.id)
        assert doc_check is not None
        assert doc_check.text == "[PURGED_DUE_TO_RETENTION_POLICY]"
