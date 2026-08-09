"""Local Filesystem Connector for ingesting files into ObjectStorageProvider."""

import mimetypes
import os
from typing import List, Optional

from pydantic import BaseModel, Field

from rag_foundry.storage.provider import ObjectStorageProvider


class RawArtifact(BaseModel):
    """Descriptor of an ingested raw artifact."""

    filename: str = Field(description="Original filename")
    storage_key: str = Field(description="Key in object storage")
    size_bytes: int = Field(description="File size in bytes")
    checksum_sha256: str = Field(description="SHA-256 digest")
    mime_type: str = Field(description="Inferred or provided MIME type")


class FilesystemConnector:
    """Connector for scanning local directories and ingesting artifacts."""

    def __init__(self, storage_provider: ObjectStorageProvider) -> None:
        """Initialize FilesystemConnector.

        Args:
            storage_provider: Storage provider instance for raw artifacts.
        """
        self.storage_provider = storage_provider

    async def ingest_file(
        self, file_path: str, custom_key: Optional[str] = None
    ) -> RawArtifact:
        """Ingest a single local file into object storage.

        Args:
            file_path: Absolute or relative path to source file.
            custom_key: Optional storage key override.

        Returns:
            RawArtifact descriptor.
        """
        abs_path = os.path.abspath(file_path)
        filename = os.path.basename(abs_path)

        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"Source file '{file_path}' not found.")

        mime_type, _ = mimetypes.guess_type(abs_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        key = custom_key or f"sources/filesystem/{filename}"

        with open(abs_path, "rb") as f:
            data = f.read()

        meta = await self.storage_provider.put_object(
            key=key, data=data, content_type=mime_type
        )
        return RawArtifact(
            filename=filename,
            storage_key=meta.key,
            size_bytes=meta.size_bytes,
            checksum_sha256=meta.checksum_sha256,
            mime_type=mime_type,
        )

    async def ingest_directory(
        self, source_dir: str, recursive: bool = True
    ) -> List[RawArtifact]:
        """Scan a directory and ingest all files into object storage.

        Args:
            source_dir: Source directory path.
            recursive: Whether to scan subdirectories recursively.

        Returns:
            List of ingested RawArtifact descriptors.
        """
        abs_dir = os.path.abspath(source_dir)
        if not os.path.isdir(abs_dir):
            raise FileNotFoundError(
                f"Source directory '{source_dir}' not found."
            )

        artifacts: List[RawArtifact] = []

        if recursive:
            for root, _, files in os.walk(abs_dir):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(file_path, abs_dir)
                    key = f"sources/filesystem/{rel_path}"
                    artifact = await self.ingest_file(
                        file_path=file_path, custom_key=key
                    )
                    artifacts.append(artifact)
        else:
            for filename in os.listdir(abs_dir):
                file_path = os.path.join(abs_dir, filename)
                if os.path.isfile(file_path):
                    key = f"sources/filesystem/{filename}"
                    artifact = await self.ingest_file(
                        file_path=file_path, custom_key=key
                    )
                    artifacts.append(artifact)

        return artifacts
