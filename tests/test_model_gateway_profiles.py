"""Unit tests for ModelProfile models and InMemoryModelProfileRegistry."""

import pytest
from pydantic import ValidationError


def test_model_profile_and_request_validation() -> None:
    """ModelProfile and ChatGenerationRequest validate fields strictly."""
    from rag_foundry.model_gateway.models import (
        ChatGenerationRequest,
        ChatMessage,
        InferenceSettings,
        ModelProfile,
    )

    profile = ModelProfile(
        profile_id="balanced-local",
        version="1.0.0",
        task="chat_generation",
        provider="ollama",
        model_name="llama3.1:8b",
        model_revision="sha256:abc123",
        base_url="http://localhost:11434",
        deployment_policy="local_only",
        data_handling_class="restricted",
        status="approved",
        inference_settings=InferenceSettings(
            temperature=0.1,
            max_tokens=2048,
            timeout_seconds=45.0,
            json_mode=True,
        ),
    )
    assert profile.profile_id == "balanced-local"
    assert profile.base_url == "http://localhost:11434"
    assert profile.inference_settings.temperature == 0.1

    # HTTP providers require a valid http/https base_url
    with pytest.raises(ValidationError):
        ModelProfile(
            profile_id="missing-url",
            version="1.0.0",
            task="chat_generation",
            provider="ollama",
            model_name="llama3.1:8b",
        )

    with pytest.raises(ValidationError):
        ModelProfile(
            profile_id="bad-scheme",
            version="1.0.0",
            task="chat_generation",
            provider="openai_compatible",
            model_name="qwen2.5",
            base_url="ftp://localhost:8000",
        )

    # Invalid status / task / blank identifiers fail validation
    with pytest.raises(ValidationError):
        ModelProfile(
            profile_id="  ",
            version="1.0.0",
            task="chat_generation",
            provider="mock",
            model_name="mock-v1",
        )

    with pytest.raises(ValidationError):
        ModelProfile(
            profile_id="bad-status",
            version="1.0.0",
            task="chat_generation",
            provider="mock",
            model_name="mock-v1",
            status="active",  # type: ignore[arg-type]
        )

    # ChatGenerationRequest forbids ad-hoc endpoints or API keys (ADR-0006)
    req = ChatGenerationRequest(
        profile_id="balanced-local",
        messages=[ChatMessage(role="user", content="Summarize policy.")],
    )
    assert req.task == "chat_generation"

    with pytest.raises(ValidationError):
        ChatGenerationRequest(
            profile_id="balanced-local",
            messages=[ChatMessage(role="user", content="Hello")],
            api_key="sk-user-supplied",  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError):
        ChatGenerationRequest(
            profile_id="balanced-local",
            messages=[ChatMessage(role="user", content="Hello")],
            base_url="https://evil.example.com",  # type: ignore[call-arg]
        )


def test_in_memory_registry_protocol_versioning_and_lifecycle() -> None:
    """InMemoryModelProfileRegistry enforces uniqueness and transitions."""
    from rag_foundry.model_gateway.models import (
        DuplicateModelProfileError,
        ModelProfile,
        ModelProfileNotFoundError,
    )
    from rag_foundry.model_gateway.registry import (
        InMemoryModelProfileRegistry,
        ModelProfileRepository,
    )

    registry = InMemoryModelProfileRegistry()
    assert isinstance(registry, ModelProfileRepository)

    v1 = ModelProfile(
        profile_id="balanced-local",
        version="1.0.0",
        task="chat_generation",
        provider="ollama",
        model_name="llama3.1:8b",
        base_url="http://localhost:11434",
        status="draft",
    )
    v2 = ModelProfile(
        profile_id="balanced-local",
        version="1.1.0",
        task="chat_generation",
        provider="ollama",
        model_name="llama3.1:8b",
        model_revision="rev-2",
        base_url="http://localhost:11434",
        status="draft",
    )
    decomp = ModelProfile(
        profile_id="fast-local",
        version="1.0.0",
        task="query_decomposition",
        provider="mock",
        model_name="mock-fast",
        status="approved",
    )

    registry.register(v1)
    registry.register(v2)
    registry.register(decomp)

    # Duplicate (profile_id, version) rejected
    with pytest.raises(DuplicateModelProfileError):
        registry.register(v1)

    # Approve v1 -> unversioned lookup returns approved v1 over draft v2
    approved_v1 = registry.approve("balanced-local", "1.0.0")
    assert approved_v1.status == "approved"
    resolved = registry.get("balanced-local")
    assert resolved is not None
    assert resolved.version == "1.0.0"
    assert resolved.status == "approved"

    # Approving v2 makes v2 the latest approved version
    registry.approve("balanced-local", "1.1.0")
    resolved_latest = registry.get("balanced-local")
    assert resolved_latest is not None
    assert resolved_latest.version == "1.1.0"

    # Exact version lookup still resolves v1
    exact_v1 = registry.get("balanced-local", version="1.0.0")
    assert exact_v1 is not None
    assert exact_v1.version == "1.0.0"

    # Deprecating v2 falls back unversioned lookup to approved v1
    dep_v2 = registry.deprecate("balanced-local", "1.1.0")
    assert dep_v2.status == "deprecated"
    after_dep = registry.get("balanced-local")
    assert after_dep is not None
    assert after_dep.version == "1.0.0"

    # Filtering by task and status returns deterministic order
    approved_chat = registry.list_profiles(
        task="chat_generation", status="approved"
    )
    assert [(p.profile_id, p.version) for p in approved_chat] == [
        ("balanced-local", "1.0.0")
    ]
    all_profiles = registry.list_profiles()
    assert len(all_profiles) == 3

    # Unknown profile lookup & lifecycle errors
    assert registry.get("unknown-profile") is None
    with pytest.raises(ModelProfileNotFoundError):
        registry.approve("unknown-profile", "1.0.0")
    with pytest.raises(ModelProfileNotFoundError):
        registry.deprecate("balanced-local", "9.9.9")


def test_registry_default_local_presets() -> None:
    """InMemoryModelProfileRegistry.with_local_defaults seeds local profiles."""
    from rag_foundry.model_gateway.registry import InMemoryModelProfileRegistry

    reg = InMemoryModelProfileRegistry.with_local_defaults()
    fast = reg.get("fast-local")
    balanced = reg.get("balanced-local")
    high_acc = reg.get("high-accuracy-private")

    assert fast is not None and fast.deployment_policy == "local_only"
    assert balanced is not None and balanced.status == "approved"
    assert high_acc is not None and high_acc.status == "approved"
