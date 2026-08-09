"""Integration tests for IngestionPipeline, database job tracking, and async execution."""

import uuid

import pytest


@pytest.mark.asyncio
async def test_ingestion_pipeline_end_to_end(sample_pdf_bytes):
    """Test IngestionPipeline processing raw PDF bytes, saving to storage and DB."""
    from rag_foundry.db.models import Base, Document
    from rag_foundry.db.session import get_sessionmaker
    from rag_foundry.ingestion.pipeline import (
        IngestionJobStatus,
        IngestionPipeline,
    )
    from rag_foundry.storage.provider import LocalStorageProvider
    import tempfile

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = LocalStorageProvider(base_path=tmp_dir)
            pipeline = IngestionPipeline(
                storage_provider=storage, session=session
            )

            workspace_id = uuid.uuid4()
            profile_id = uuid.uuid4()

            result = await pipeline.process_file(
                file_bytes=sample_pdf_bytes,
                filename="architecture_report.pdf",
                mime_type="application/pdf",
                workspace_id=workspace_id,
                semantic_profile_id=profile_id,
            )

            assert result.status == IngestionJobStatus.PARSED
            assert result.canonical_document is not None
            assert result.diagnostics is not None
            assert result.canonical_document.page_count == 1

            # Verify object storage
            assert await storage.object_exists(result.storage_key) is True

            # Verify DB Document record
            doc_record = await session.get(Document, result.document_id)
            assert doc_record is not None
            assert doc_record.title == "architecture_report.pdf"
            assert doc_record.parser_name == "native_pdf"


@pytest.mark.asyncio
async def test_ingestion_pipeline_handles_failure():
    """Test IngestionPipeline updates DB status to FAILED when parsing invalid bytes."""
    from rag_foundry.db.models import Base
    from rag_foundry.db.session import get_sessionmaker
    from rag_foundry.ingestion.pipeline import (
        IngestionJobStatus,
        IngestionPipeline,
    )
    from rag_foundry.storage.provider import LocalStorageProvider
    import tempfile

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = LocalStorageProvider(base_path=tmp_dir)
            pipeline = IngestionPipeline(
                storage_provider=storage, session=session
            )

            result = await pipeline.process_file(
                file_bytes=b"Corrupted PDF data",
                filename="corrupted.pdf",
                mime_type="application/pdf",
                workspace_id=uuid.uuid4(),
                semantic_profile_id=uuid.uuid4(),
            )

            assert result.status == IngestionJobStatus.FAILED
            assert result.error_message is not None
