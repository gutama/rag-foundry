"""Unit tests for FilesystemConnector and ingestion source connectors."""

import os
import tempfile
import pytest


@pytest.mark.asyncio
async def test_filesystem_connector_scan_and_ingest():
    """Test FilesystemConnector scanning directory files and ingesting to storage."""
    from rag_foundry.connectors.filesystem import FilesystemConnector
    from rag_foundry.storage.provider import LocalStorageProvider

    with tempfile.TemporaryDirectory() as storage_dir, tempfile.TemporaryDirectory() as source_dir:
        # Create test source files
        file1 = os.path.join(source_dir, "report1.pdf")
        file2 = os.path.join(source_dir, "data.docx")
        with open(file1, "wb") as f:
            f.write(b"PDF report sample content")
        with open(file2, "wb") as f:
            f.write(b"DOCX document sample content")

        storage = LocalStorageProvider(base_path=storage_dir)
        connector = FilesystemConnector(storage_provider=storage)

        artifacts = await connector.ingest_directory(source_dir=source_dir)
        assert len(artifacts) == 2

        keys = [a.storage_key for a in artifacts]
        assert any("report1.pdf" in k for k in keys)
        assert any("data.docx" in k for k in keys)

        # Check stored content
        stored_bytes = await storage.get_object(artifacts[0].storage_key)
        assert len(stored_bytes) > 0
