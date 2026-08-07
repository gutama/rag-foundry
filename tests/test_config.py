import pytest

def test_settings_load():
    from rag_foundry.core.config import Settings

    settings = Settings(
        postgres_dsn="postgresql+asyncpg://user:pass@localhost:5432/rag_foundry_test",
        environment="testing",
    )
    assert settings.environment == "testing"
    assert "postgresql+asyncpg" in str(settings.postgres_dsn)
