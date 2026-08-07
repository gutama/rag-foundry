from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Core application settings for RAG Foundry."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    environment: str = Field(default="development", description="Execution environment (development, testing, production)")
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://rag_user:rag_pass@localhost:5432/rag_foundry",
        description="Async PostgreSQL connection string"
    )
    secret_key: str = Field(default="change_this_secret_in_production", description="Application secret key")
    log_level: str = Field(default="INFO", description="Logging level")
