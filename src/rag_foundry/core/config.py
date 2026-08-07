"""Core application settings for RAG Foundry."""

from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageProfile(str, Enum):
    """Deployment storage profile per ADR-0004.

    COMPACT: Single-node profile using PostgreSQL, pgvector, PG FTS,
             and local filesystem.
    SCALE:   Distributed profile using Qdrant, OpenSearch, Redis,
             and enterprise object storage.
    """

    COMPACT = "compact"
    SCALE = "scale"


class Settings(BaseSettings):
    """Core application settings for RAG Foundry.

    All settings can be overridden via environment variables or a .env file.
    Security-sensitive fields (postgres_dsn, secret_key) have no defaults
    and must be explicitly configured to prevent accidental deployment
    with development credentials.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field(
        default="development",
        description="Execution environment (development, testing, production)",
    )
    storage_profile: StorageProfile = Field(
        default=StorageProfile.COMPACT,
        description=(
            "Storage profile: compact (single-node) or scale (distributed)"
        ),
    )
    postgres_dsn: str = Field(
        description="Async PostgreSQL connection string",
    )
    secret_key: str = Field(
        description="Application secret key",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
