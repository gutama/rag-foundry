"""Unit tests for ObjectStorageProvider (Local and S3/MinIO backends)."""

import io
import os
import tempfile
import pytest


@pytest.mark.asyncio
async def test_local_storage_provider_put_and_get():
    """Test putting an object into LocalStorageProvider and reading it back."""
    from rag_foundry.storage.provider import LocalStorageProvider

    with tempfile.TemporaryDirectory() as tmp_dir:
        provider = LocalStorageProvider(base_path=tmp_dir)
        data = b"Hello, RAG Foundry Object Storage!"
        storage_key = "artifacts/doc_001.pdf"

        meta = await provider.put_object(
            key=storage_key, data=data, content_type="application/pdf"
        )
        assert meta.key == storage_key
        assert meta.size_bytes == len(data)
        assert meta.checksum_sha256 is not None

        retrieved = await provider.get_object(key=storage_key)
        assert retrieved == data

        exists = await provider.object_exists(key=storage_key)
        assert exists is True


@pytest.mark.asyncio
async def test_local_storage_provider_delete():
    """Test deleting an object from LocalStorageProvider."""
    from rag_foundry.storage.provider import LocalStorageProvider

    with tempfile.TemporaryDirectory() as tmp_dir:
        provider = LocalStorageProvider(base_path=tmp_dir)
        key = "test/delete_me.txt"
        await provider.put_object(key=key, data=b"temp data")

        assert await provider.object_exists(key) is True
        deleted = await provider.delete_object(key=key)
        assert deleted is True
        assert await provider.object_exists(key) is False
