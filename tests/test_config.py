"""Tests for core configuration module."""

import pytest

from rag_foundry.core.config import Settings, StorageProfile


class TestSettings:
    """Tests for the Settings configuration class."""

    def test_settings_load_with_required_fields(self):
        """Settings loads correctly when all required fields are provided."""
        settings = Settings(
            postgres_dsn=(
                "postgresql+asyncpg://user:pass@localhost:5432/rag_test"
            ),
            secret_key="test-secret-key",
            environment="testing",
        )
        assert settings.environment == "testing"
        assert "postgresql+asyncpg" in settings.postgres_dsn
        assert settings.secret_key == "test-secret-key"

    def test_settings_defaults(self):
        """Fields with defaults use their default values."""
        settings = Settings(
            postgres_dsn=(
                "postgresql+asyncpg://user:pass@localhost:5432/rag_test"
            ),
            secret_key="test-secret-key",
        )
        assert settings.environment == "development"
        assert settings.log_level == "INFO"
        assert settings.storage_profile == StorageProfile.COMPACT

    def test_settings_missing_postgres_dsn_raises(self):
        """Settings raises ValidationError when postgres_dsn is missing."""
        with pytest.raises(Exception):
            Settings(secret_key="test-secret-key")

    def test_settings_missing_secret_key_raises(self):
        """Settings raises ValidationError when secret_key is missing."""
        with pytest.raises(Exception):
            Settings(
                postgres_dsn=(
                    "postgresql+asyncpg://user:pass@localhost:5432/rag_test"
                ),
            )

    def test_storage_profile_compact(self):
        """StorageProfile.COMPACT is accepted and stored correctly."""
        settings = Settings(
            postgres_dsn=(
                "postgresql+asyncpg://user:pass@localhost:5432/rag_test"
            ),
            secret_key="test-secret-key",
            storage_profile="compact",
        )
        assert settings.storage_profile == StorageProfile.COMPACT

    def test_storage_profile_scale(self):
        """StorageProfile.SCALE is accepted and stored correctly."""
        settings = Settings(
            postgres_dsn=(
                "postgresql+asyncpg://user:pass@localhost:5432/rag_test"
            ),
            secret_key="test-secret-key",
            storage_profile="scale",
        )
        assert settings.storage_profile == StorageProfile.SCALE

    def test_storage_profile_invalid_raises(self):
        """Invalid storage profile value raises ValidationError."""
        with pytest.raises(Exception):
            Settings(
                postgres_dsn=(
                    "postgresql+asyncpg://user:pass@localhost:5432/rag_test"
                ),
                secret_key="test-secret-key",
                storage_profile="invalid_profile",
            )

    def test_environment_override(self):
        """Environment field can be overridden."""
        settings = Settings(
            postgres_dsn=(
                "postgresql+asyncpg://user:pass@localhost:5432/rag_test"
            ),
            secret_key="test-secret-key",
            environment="production",
        )
        assert settings.environment == "production"

    def test_log_level_override(self):
        """Log level field can be overridden."""
        settings = Settings(
            postgres_dsn=(
                "postgresql+asyncpg://user:pass@localhost:5432/rag_test"
            ),
            secret_key="test-secret-key",
            log_level="DEBUG",
        )
        assert settings.log_level == "DEBUG"

    def test_extra_fields_ignored(self):
        """Extra fields are ignored per SettingsConfigDict(extra='ignore')."""
        settings = Settings(
            postgres_dsn=(
                "postgresql+asyncpg://user:pass@localhost:5432/rag_test"
            ),
            secret_key="test-secret-key",
            nonexistent_field="should_be_ignored",
        )
        assert not hasattr(settings, "nonexistent_field")
