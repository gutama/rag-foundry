"""Domain models and typed exceptions for the Model Gateway (ADR-0006)."""

from datetime import datetime, timezone
from typing import Literal, Optional, Tuple
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

ModelTask = Literal[
    "chat_generation",
    "query_decomposition",
    "embeddings",
    "reranking",
    "metadata_extraction",
    "taxonomy_classification",
    "entity_extraction",
    "evaluation_judge",
]

ModelProvider = Literal["ollama", "openai_compatible", "mock"]
ModelProfileStatus = Literal["draft", "approved", "deprecated"]
DeploymentPolicy = Literal["local_only", "approved_remote"]
DataHandlingClass = Literal["restricted", "confidential", "internal", "public"]


class ModelGatewayError(Exception):
    """Base exception for Model Gateway configuration and policy failures."""


class DuplicateModelProfileError(ModelGatewayError):
    """Raised when registering an already-existing (profile_id, version)."""


class ModelProfileNotFoundError(ModelGatewayError):
    """Raised when a requested model profile or version does not exist."""


class ModelProfilePolicyError(ModelGatewayError):
    """Raised when a profile violates approval, task, or network policy."""


class ModelAdapterError(ModelGatewayError):
    """Raised when a chat provider adapter encounters transport/parse errors."""


class InferenceSettings(BaseModel):
    """Server-controlled inference hyperparameters for a ModelProfile."""

    model_config = ConfigDict(frozen=True)

    temperature: float = Field(
        default=0.0, ge=0.0, le=2.0, description="Sampling temperature."
    )
    max_tokens: int = Field(
        default=1024, ge=1, le=65536, description="Maximum output tokens."
    )
    top_p: Optional[float] = Field(
        default=None, gt=0.0, le=1.0, description="Optional nucleus sampling."
    )
    timeout_seconds: float = Field(
        default=60.0, gt=0.0, description="HTTP/inference timeout in seconds."
    )
    json_mode: bool = Field(
        default=True,
        description="Whether to request structured JSON output by default.",
    )
    seed: Optional[int] = Field(
        default=None,
        description="Optional deterministic generation seed when supported.",
    )


class ModelProfile(BaseModel):
    """Approved, versioned model profile governed by ADR-0006."""

    model_config = ConfigDict(frozen=True)

    profile_id: str = Field(description="Stable server-controlled profile ID.")
    version: str = Field(description="Semantic or revision version string.")
    task: ModelTask = Field(description="Allowed workload category.")
    provider: ModelProvider = Field(description="Backend provider category.")
    model_name: str = Field(description="Provider model identifier.")
    model_revision: Optional[str] = Field(
        default=None, description="Pinned model digest or revision string."
    )
    tokenizer_name: Optional[str] = Field(
        default=None, description="Optional tokenizer identifier."
    )
    data_handling_class: DataHandlingClass = Field(
        default="confidential",
        description="Maximum data sensitivity classification allowed.",
    )
    deployment_policy: DeploymentPolicy = Field(
        default="local_only",
        description="Network boundary policy (local_only or approved_remote).",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Server-configured HTTP base URL for local/private hosts.",
    )
    api_key_env_var: Optional[str] = Field(
        default=None,
        description="Server-side environment variable holding optional token.",
    )
    inference_settings: InferenceSettings = Field(
        default_factory=InferenceSettings,
        description="Default inference settings pinned to this profile.",
    )
    status: ModelProfileStatus = Field(
        default="draft",
        description="Lifecycle status (draft, approved, or deprecated).",
    )
    description: Optional[str] = Field(
        default=None, description="Human-readable profile purpose."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC creation timestamp.",
    )

    @field_validator("profile_id", "version", "model_name")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        """Ensure required string identifiers are non-empty after stripping."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Identifier fields must be non-empty.")
        return cleaned

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: Optional[str]) -> Optional[str]:
        """Normalize and validate HTTP(S) base URLs when provided."""
        if value is None:
            return None
        cleaned = value.strip().rstrip("/")
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                f"Invalid HTTP(S) base_url: {value!r}."
            )
        return cleaned

    @model_validator(mode="after")
    def _validate_provider_url_requirement(self) -> "ModelProfile":
        """Require base_url for HTTP-backed model providers."""
        if self.provider in {"ollama", "openai_compatible"} and not (
            self.base_url
        ):
            raise ValueError(
                f"Provider {self.provider!r} requires a non-empty base_url."
            )
        return self


class ChatMessage(BaseModel):
    """Single message turn passed to a chat generation adapter."""

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"] = Field(
        description="Chat role."
    )
    content: str = Field(min_length=1, description="Message text content.")


class ChatGenerationRequest(BaseModel):
    """Caller request to ModelGateway; forbids ad-hoc endpoints or API keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(
        min_length=1, description="Approved server-side profile identifier."
    )
    profile_version: Optional[str] = Field(
        default=None,
        description=(
            "Optional pinned profile version (latest approved if None)."
        ),
    )
    task: ModelTask = Field(
        default="chat_generation",
        description="Requested model task validated against profile.task.",
    )
    messages: Tuple[ChatMessage, ...] = Field(
        min_length=1, description="Ordered conversation messages."
    )
    json_mode: Optional[bool] = Field(
        default=None,
        description=(
            "Optional JSON-mode override (defaults to profile setting)."
        ),
    )
    temperature: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Optional temperature override within valid bounds.",
    )
    max_tokens: Optional[int] = Field(
        default=None,
        ge=1,
        le=65536,
        description="Optional max output tokens override.",
    )

    @field_validator("profile_id")
    @classmethod
    def _validate_profile_id(cls, value: str) -> str:
        """Strip and verify non-empty profile_id."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("profile_id must be non-empty.")
        return cleaned


class TokenUsage(BaseModel):
    """Token consumption metrics reported by a chat provider."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ChatGenerationResponse(BaseModel):
    """Structured response with full model-profile reproducibility trace."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(description="Raw text or JSON string from the model.")
    profile_id: str = Field(description="Resolved approved profile ID.")
    profile_version: str = Field(description="Resolved profile version.")
    provider: ModelProvider = Field(description="Executed provider category.")
    model_name: str = Field(description="Executed model identifier.")
    model_revision: Optional[str] = Field(
        default=None, description="Pinned model revision or digest."
    )
    finish_reason: Optional[str] = Field(
        default=None, description="Provider completion finish reason."
    )
    usage: TokenUsage = Field(
        default_factory=TokenUsage, description="Reported token usage."
    )
    duration_ms: float = Field(
        default=0.0, ge=0.0, description="End-to-end generation latency in ms."
    )
