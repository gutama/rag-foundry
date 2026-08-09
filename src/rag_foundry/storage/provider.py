"""Abstract ObjectStorageProvider and LocalStorageProvider implementation."""

import hashlib
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class ObjectMetadata(BaseModel):
    """Metadata describing a stored object artifact."""

    key: str = Field(description="Storage key or relative object path")
    size_bytes: int = Field(description="Size in bytes")
    checksum_sha256: str = Field(description="SHA-256 digest hex string")
    content_type: Optional[str] = Field(
        default=None, description="MIME content type"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Object creation timestamp",
    )


class ObjectStorageProvider(ABC):
    """Abstract provider interface for raw object artifact storage."""

    @abstractmethod
    async def put_object(
        self, key: str, data: bytes, content_type: Optional[str] = None
    ) -> ObjectMetadata:
        """Store an object by key."""
        pass

    @abstractmethod
    async def get_object(self, key: str) -> bytes:
        """Retrieve object content bytes by key."""
        pass

    @abstractmethod
    async def delete_object(self, key: str) -> bool:
        """Delete an object by key."""
        pass

    @abstractmethod
    async def object_exists(self, key: str) -> bool:
        """Check if an object exists by key."""
        pass


class LocalStorageProvider(ObjectStorageProvider):
    """Local filesystem implementation of ObjectStorageProvider."""

    def __init__(self, base_path: str) -> None:
        """Initialize LocalStorageProvider.

        Args:
            base_path: Base directory path for storing artifacts.
        """
        self.base_path = os.path.abspath(base_path)
        os.makedirs(self.base_path, exist_ok=True)

    def _get_full_path(self, key: str) -> str:
        """Resolve full filesystem path for a relative key."""
        clean_key = key.lstrip("/\\")
        full_path = os.path.abspath(os.path.join(self.base_path, clean_key))
        if not full_path.startswith(self.base_path):
            raise ValueError(f"Path traversal detected for key '{key}'.")
        return full_path

    async def put_object(
        self, key: str, data: bytes, content_type: Optional[str] = None
    ) -> ObjectMetadata:
        """Store object bytes to local disk.

        Args:
            key: Storage key.
            data: Raw bytes to write.
            content_type: Optional MIME content type.

        Returns:
            ObjectMetadata descriptor.
        """
        full_path = self._get_full_path(key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "wb") as f:
            f.write(data)

        checksum = hashlib.sha256(data).hexdigest()
        return ObjectMetadata(
            key=key,
            size_bytes=len(data),
            checksum_sha256=checksum,
            content_type=content_type,
        )

    async def get_object(self, key: str) -> bytes:
        """Read object bytes from local disk.

        Args:
            key: Storage key.

        Returns:
            Object content bytes.

        Raises:
            FileNotFoundError: If object key does not exist.
        """
        full_path = self._get_full_path(key)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Object key '{key}' not found.")

        with open(full_path, "rb") as f:
            return f.read()

    async def delete_object(self, key: str) -> bool:
        """Delete object file from local disk.

        Args:
            key: Storage key.

        Returns:
            True if deleted, False if file did not exist.
        """
        full_path = self._get_full_path(key)
        if os.path.exists(full_path):
            os.remove(full_path)
            return True
        return False

    async def object_exists(self, key: str) -> bool:
        """Check if object file exists on local disk.

        Args:
            key: Storage key.

        Returns:
            True if file exists.
        """
        full_path = self._get_full_path(key)
        return os.path.exists(full_path)
