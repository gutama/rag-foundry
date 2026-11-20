"""Unit tests for fail-closed ModelGateway enforcement and async execution."""

import asyncio
import time
from typing import Any, Dict, Sequence

import pytest

from rag_foundry.model_gateway.adapters import (
    AdapterCompletionResult,
    MockDeterministicChatAdapter,
    OllamaChatAdapter,
    OpenAICompatibleChatAdapter,
)
from rag_foundry.model_gateway.models import (
    ChatGenerationRequest,
    ChatMessage,
    InferenceSettings,
    ModelProfile,
    ModelProfileNotFoundError,
    ModelProfilePolicyError,
    ModelProvider,
    TokenUsage,
)
from rag_foundry.model_gateway.registry import InMemoryModelProfileRegistry


def _msg(text: str = "Summarize [E1].") -> tuple[ChatMessage, ...]:
    """Create a single-turn user message tuple."""
    return (ChatMessage(role="user", content=text),)


def test_is_local_or_private_host_boundary_rules() -> None:
    """Host validator allows loopback/private/local and rejects public URLs."""
    from rag_foundry.model_gateway.gateway import is_local_or_private_host

    # Allowed local / private / in-cluster endpoints
    for allowed in [
        "http://localhost:11434",
        "http://127.0.0.1:8000",
        "http://[::1]:11434",
        "http://10.0.1.25:8000",
        "http://172.16.4.12:8000",
        "http://192.168.1.50:11434",
        "http://ollama:11434",
        "http://vllm-service.internal:8000",
        "https://inference.cluster.local:8443",
        "http://host.docker.internal:11434",
    ]:
        assert is_local_or_private_host(allowed) is True, allowed

    # Disallowed public / unspecified / decimal-encoded IP endpoints
    for blocked in [
        "https://api.openai.com/v1",
        "https://api.anthropic.com",
        "https://8.8.8.8:443",
        "http://0.0.0.0:8000",
        "http://2130706433:8000",
        "https://evil.example.com",
    ]:
        assert is_local_or_private_host(blocked) is False, blocked


@pytest.mark.asyncio
async def test_gateway_fails_closed_on_unknown_unapproved_or_mismatch() -> None:
    """Gateway rejects missing, draft, deprecated, and task-mismatched IDs."""
    from rag_foundry.model_gateway.gateway import ModelGateway

    registry = InMemoryModelProfileRegistry(
        profiles=[
            ModelProfile(
                profile_id="draft-prof",
                version="1.0.0",
                task="chat_generation",
                provider="mock",
                model_name="mock-v1",
                status="draft",
            ),
            ModelProfile(
                profile_id="old-prof",
                version="1.0.0",
                task="chat_generation",
                provider="mock",
                model_name="mock-v0",
                status="deprecated",
            ),
            ModelProfile(
                profile_id="decomp-only",
                version="1.0.0",
                task="query_decomposition",
                provider="mock",
                model_name="mock-decomp",
                status="approved",
            ),
        ]
    )
    gateway = ModelGateway(registry=registry)

    # Unknown profile
    with pytest.raises(ModelProfileNotFoundError):
        await gateway.generate(
            ChatGenerationRequest(profile_id="does-not-exist", messages=_msg())
        )

    # Draft profile rejected
    with pytest.raises(ModelProfilePolicyError, match="draft"):
        await gateway.generate(
            ChatGenerationRequest(profile_id="draft-prof", messages=_msg())
        )

    # Deprecated profile rejected
    with pytest.raises(ModelProfilePolicyError, match="deprecated"):
        await gateway.generate(
            ChatGenerationRequest(profile_id="old-prof", messages=_msg())
        )

    # Task mismatch rejected
    with pytest.raises(ModelProfilePolicyError, match="task"):
        await gateway.generate(
            ChatGenerationRequest(
                profile_id="decomp-only",
                task="chat_generation",
                messages=_msg(),
            )
        )


@pytest.mark.asyncio
async def test_gateway_enforces_local_only_and_remote_allowlist() -> None:
    """local_only rejects public URLs; approved_remote requires opt-in."""
    from rag_foundry.model_gateway.gateway import ModelGateway

    bad_local = ModelProfile(
        profile_id="misconfigured-local",
        version="1.0.0",
        task="chat_generation",
        provider="openai_compatible",
        model_name="gpt-4o",
        base_url="https://api.openai.com",
        deployment_policy="local_only",
        status="approved",
    )
    approved_remote = ModelProfile(
        profile_id="approved-cloud",
        version="1.0.0",
        task="chat_generation",
        provider="openai_compatible",
        model_name="private-cloud-llm",
        base_url="https://llm.trusted-partner.example",
        deployment_policy="approved_remote",
        status="approved",
    )
    registry = InMemoryModelProfileRegistry(
        profiles=[bad_local, approved_remote]
    )

    transport_calls = 0

    def fake_transport(
        _u: str, _p: Dict[str, Any], _h: Dict[str, str], _t: float
    ) -> Dict[str, Any]:
        nonlocal transport_calls
        transport_calls += 1
        return {
            "choices": [
                {
                    "message": {"content": '{"answer": "ok"}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }

    # Air-gapped default gateway blocks both misconfigured local and remote
    airgapped = ModelGateway(
        registry=registry,
        adapters={
            "openai_compatible": OpenAICompatibleChatAdapter(
                transport=fake_transport
            )
        },
    )
    with pytest.raises(ModelProfilePolicyError, match="local_only"):
        await airgapped.generate(
            ChatGenerationRequest(
                profile_id="misconfigured-local", messages=_msg()
            )
        )
    with pytest.raises(ModelProfilePolicyError, match="remote"):
        await airgapped.generate(
            ChatGenerationRequest(
                profile_id="approved-cloud", messages=_msg()
            )
        )
    assert transport_calls == 0

    # Explicit opt-in with host allowlist permits only allowed remote host
    remote_gw = ModelGateway(
        registry=registry,
        adapters={
            "openai_compatible": OpenAICompatibleChatAdapter(
                transport=fake_transport
            )
        },
        allow_approved_remote=True,
        allowed_remote_hosts={"llm.trusted-partner.example"},
    )
    resp = await remote_gw.generate(
        ChatGenerationRequest(profile_id="approved-cloud", messages=_msg())
    )
    assert resp.content == '{"answer": "ok"}'
    assert transport_calls == 1

    # Host outside allowlist still fails closed
    wrong_allowlist_gw = ModelGateway(
        registry=registry,
        adapters={
            "openai_compatible": OpenAICompatibleChatAdapter(
                transport=fake_transport
            )
        },
        allow_approved_remote=True,
        allowed_remote_hosts={"other.trusted-partner.example"},
    )
    with pytest.raises(ModelProfilePolicyError, match="allowlist"):
        await wrong_allowlist_gw.generate(
            ChatGenerationRequest(profile_id="approved-cloud", messages=_msg())
        )

    # Missing adapter for a provider fails closed (never falls back silently)
    no_ollama_gw = ModelGateway(
        registry=InMemoryModelProfileRegistry.with_local_defaults(),
        adapters={"mock": MockDeterministicChatAdapter()},
    )
    with pytest.raises(ModelProfilePolicyError, match="adapter"):
        await no_ollama_gw.generate(
            ChatGenerationRequest(profile_id="balanced-local", messages=_msg())
        )


@pytest.mark.asyncio
async def test_gateway_returns_reproducibility_trace_and_overrides() -> None:
    """Gateway populates full reproducibility metadata on response."""
    from rag_foundry.model_gateway.gateway import ModelGateway

    captured_payload: Dict[str, Any] = {}

    def fake_ollama(
        _u: str, payload: Dict[str, Any], _h: Dict[str, str], _t: float
    ) -> Dict[str, Any]:
        captured_payload.update(payload)
        return {
            "message": {"content": '{"answer": "Grounded [E1]."}'},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 40,
            "eval_count": 12,
        }

    profile = ModelProfile(
        profile_id="balanced-local",
        version="2.0.0",
        task="chat_generation",
        provider="ollama",
        model_name="llama3.1:8b",
        model_revision="sha256:999abc",
        base_url="http://127.0.0.1:11434",
        deployment_policy="local_only",
        status="approved",
        inference_settings=InferenceSettings(
            temperature=0.0, max_tokens=1024, json_mode=True
        ),
    )
    registry = InMemoryModelProfileRegistry(profiles=[profile])
    gateway = ModelGateway(
        registry=registry,
        adapters={"ollama": OllamaChatAdapter(transport=fake_ollama)},
    )

    resp = await gateway.generate(
        ChatGenerationRequest(
            profile_id="balanced-local",
            profile_version="2.0.0",
            messages=_msg(),
            temperature=0.25,
            max_tokens=300,
            json_mode=False,
        )
    )

    assert resp.profile_id == "balanced-local"
    assert resp.profile_version == "2.0.0"
    assert resp.provider == "ollama"
    assert resp.model_name == "llama3.1:8b"
    assert resp.model_revision == "sha256:999abc"
    assert resp.finish_reason == "stop"
    assert resp.usage.prompt_tokens == 40
    assert resp.usage.completion_tokens == 12
    assert resp.usage.total_tokens == 52
    assert resp.duration_ms >= 0.0
    assert captured_payload["options"]["temperature"] == 0.25
    assert captured_payload["options"]["num_predict"] == 300
    assert "format" not in captured_payload


@pytest.mark.asyncio
async def test_gateway_offloads_blocking_adapter_via_to_thread() -> None:
    """Slow blocking adapter execution does not stall the asyncio loop."""
    from rag_foundry.model_gateway.gateway import ModelGateway

    class _SlowBlockingAdapter:
        provider: ModelProvider = "mock"

        def generate(
            self,
            profile: ModelProfile,
            messages: Sequence[ChatMessage],
            *,
            json_mode: bool,
            temperature: float,
            max_tokens: int,
        ) -> AdapterCompletionResult:
            del profile, messages, json_mode, temperature, max_tokens
            time.sleep(0.15)
            return AdapterCompletionResult(
                content='{"answer": "done"}',
                finish_reason="stop",
                usage=TokenUsage(
                    prompt_tokens=1, completion_tokens=1, total_tokens=2
                ),
            )

    profile = ModelProfile(
        profile_id="slow-mock",
        version="1.0.0",
        task="chat_generation",
        provider="mock",
        model_name="slow-v1",
        status="approved",
    )
    gateway = ModelGateway(
        registry=InMemoryModelProfileRegistry(profiles=[profile]),
        adapters={"mock": _SlowBlockingAdapter()},
    )

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.02)
            ticks += 1

    resp, _ = await asyncio.gather(
        gateway.generate(
            ChatGenerationRequest(profile_id="slow-mock", messages=_msg())
        ),
        ticker(),
    )
    assert resp.content == '{"answer": "done"}'
    assert ticks == 5
    assert resp.duration_ms >= 100.0
