"""Unit tests for stdlib HTTP chat adapters and deterministic mock adapter."""

import io
import json
import urllib.error
from typing import Any, Dict, List, Tuple

import pytest

from rag_foundry.model_gateway.models import (
    ChatMessage,
    InferenceSettings,
    ModelProfile,
)


def _ollama_profile(
    *,
    base_url: str = "http://localhost:11434",
    top_p: float | None = 0.9,
    seed: int | None = 42,
) -> ModelProfile:
    """Create a sample approved Ollama ModelProfile."""
    return ModelProfile(
        profile_id="balanced-local",
        version="1.0.0",
        task="chat_generation",
        provider="ollama",
        model_name="llama3.1:8b",
        base_url=base_url,
        deployment_policy="local_only",
        status="approved",
        inference_settings=InferenceSettings(
            temperature=0.0,
            max_tokens=512,
            top_p=top_p,
            seed=seed,
            timeout_seconds=30.0,
            json_mode=True,
        ),
    )


def _openai_compat_profile(
    *,
    base_url: str = "http://localhost:8000",
    api_key_env_var: str | None = None,
) -> ModelProfile:
    """Create a sample approved OpenAI-compatible ModelProfile."""
    return ModelProfile(
        profile_id="vllm-local",
        version="1.0.0",
        task="chat_generation",
        provider="openai_compatible",
        model_name="qwen2.5:32b-instruct",
        base_url=base_url,
        api_key_env_var=api_key_env_var,
        deployment_policy="local_only",
        status="approved",
        inference_settings=InferenceSettings(
            temperature=0.2,
            max_tokens=1024,
            top_p=0.95,
            seed=7,
            timeout_seconds=45.0,
            json_mode=True,
        ),
    )


def _mock_profile() -> ModelProfile:
    """Create a sample approved mock ModelProfile."""
    return ModelProfile(
        profile_id="mock-qa",
        version="1.0.0",
        task="chat_generation",
        provider="mock",
        model_name="mock-grounded-v1",
        deployment_policy="local_only",
        status="approved",
    )


def test_adapters_satisfy_chat_model_adapter_protocol() -> None:
    """All chat adapters conform to runtime-checkable ChatModelAdapter."""
    from rag_foundry.model_gateway.adapters import (
        ChatModelAdapter,
        MockDeterministicChatAdapter,
        OllamaChatAdapter,
        OpenAICompatibleChatAdapter,
    )

    ollama = OllamaChatAdapter()
    openai_compat = OpenAICompatibleChatAdapter()
    mock = MockDeterministicChatAdapter()

    assert isinstance(ollama, ChatModelAdapter)
    assert isinstance(openai_compat, ChatModelAdapter)
    assert isinstance(mock, ChatModelAdapter)
    assert ollama.provider == "ollama"
    assert openai_compat.provider == "openai_compatible"
    assert mock.provider == "mock"


def test_ollama_chat_adapter_payload_and_response() -> None:
    """OllamaChatAdapter formats /api/chat payload and parses token usage."""
    from rag_foundry.model_gateway.adapters import (
        ModelAdapterError,
        OllamaChatAdapter,
    )

    captured: List[Tuple[str, Dict[str, Any], Dict[str, str], float]] = []

    def fake_transport(
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: float,
    ) -> Dict[str, Any]:
        captured.append((url, payload, headers, timeout))
        return {
            "message": {
                "role": "assistant",
                "content": '{"answer": "Supported [E1]."}',
            },
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 120,
            "eval_count": 30,
        }

    adapter = OllamaChatAdapter(transport=fake_transport)
    profile = _ollama_profile()
    msgs = (
        ChatMessage(role="system", content="Respond in JSON."),
        ChatMessage(role="user", content="Explain [E1]."),
    )

    result = adapter.generate(
        profile,
        msgs,
        json_mode=True,
        temperature=0.0,
        max_tokens=256,
    )

    assert len(captured) == 1
    url, payload, headers, timeout = captured[0]
    assert url == "http://localhost:11434/api/chat"
    assert timeout == 30.0
    assert headers["Content-Type"] == "application/json"
    assert payload["model"] == "llama3.1:8b"
    assert payload["stream"] is False
    assert payload["format"] == "json"
    assert payload["options"] == {
        "temperature": 0.0,
        "num_predict": 256,
        "top_p": 0.9,
        "seed": 42,
    }
    assert len(payload["messages"]) == 2
    assert result.content == '{"answer": "Supported [E1]."}'
    assert result.finish_reason == "stop"
    assert result.usage.prompt_tokens == 120
    assert result.usage.completion_tokens == 30
    assert result.usage.total_tokens == 150

    # Plain-text mode omits format="json"
    adapter.generate(
        profile,
        msgs,
        json_mode=False,
        temperature=0.3,
        max_tokens=128,
    )
    assert "format" not in captured[1][1]

    # Malformed payload raises ModelAdapterError
    bad_adapter = OllamaChatAdapter(
        transport=lambda _u, _p, _h, _t: {"done": True}
    )
    with pytest.raises(ModelAdapterError, match="missing message content"):
        bad_adapter.generate(
            profile,
            msgs,
            json_mode=True,
            temperature=0.0,
            max_tokens=64,
        )

    # Provider mismatch raises ModelAdapterError
    with pytest.raises(ModelAdapterError, match="provider"):
        adapter.generate(
            _openai_compat_profile(),
            msgs,
            json_mode=True,
            temperature=0.0,
            max_tokens=64,
        )


def test_openai_compatible_chat_adapter_payload_auth_and_errors() -> None:
    """OpenAICompatibleChatAdapter handles /v1 paths, auth, and parsing."""
    from rag_foundry.model_gateway.adapters import (
        ModelAdapterError,
        OpenAICompatibleChatAdapter,
    )

    captured: List[Tuple[str, Dict[str, Any], Dict[str, str], float]] = []

    def fake_transport(
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: float,
    ) -> Dict[str, Any]:
        captured.append((url, payload, headers, timeout))
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"answer": "Verified [A1]."}',
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 80,
                "completion_tokens": 20,
            },
        }

    adapter = OpenAICompatibleChatAdapter(
        transport=fake_transport,
        env={"PRIVATE_VLLM_KEY": "secret-token-123"},
    )
    profile = _openai_compat_profile(
        base_url="http://localhost:8000",
        api_key_env_var="PRIVATE_VLLM_KEY",
    )
    msgs = (ChatMessage(role="user", content="State rule [A1]."),)

    result = adapter.generate(
        profile,
        msgs,
        json_mode=True,
        temperature=0.1,
        max_tokens=512,
    )

    assert captured[0][0] == "http://localhost:8000/v1/chat/completions"
    assert captured[0][1]["response_format"] == {"type": "json_object"}
    assert captured[0][1]["top_p"] == 0.95
    assert captured[0][1]["seed"] == 7
    assert captured[0][2]["Authorization"] == "Bearer secret-token-123"
    assert result.content == '{"answer": "Verified [A1]."}'
    assert result.finish_reason == "stop"
    assert result.usage.prompt_tokens == 80
    assert result.usage.completion_tokens == 20
    assert result.usage.total_tokens == 100

    # Base URL ending in /v1 does not duplicate /v1
    v1_profile = _openai_compat_profile(base_url="http://localhost:8000/v1")
    adapter.generate(
        v1_profile,
        msgs,
        json_mode=False,
        temperature=0.0,
        max_tokens=100,
    )
    assert captured[1][0] == "http://localhost:8000/v1/chat/completions"
    assert "response_format" not in captured[1][1]
    assert "Authorization" not in captured[1][2]

    # Missing configured server-side env var fails closed
    missing_env_adapter = OpenAICompatibleChatAdapter(
        transport=fake_transport,
        env={},
    )
    with pytest.raises(ModelAdapterError, match="PRIVATE_VLLM_KEY"):
        missing_env_adapter.generate(
            profile,
            msgs,
            json_mode=True,
            temperature=0.0,
            max_tokens=64,
        )

    # Empty choices fails closed
    empty_adapter = OpenAICompatibleChatAdapter(
        transport=lambda _u, _p, _h, _t: {"choices": []}
    )
    with pytest.raises(ModelAdapterError, match="choices"):
        empty_adapter.generate(
            v1_profile,
            msgs,
            json_mode=True,
            temperature=0.0,
            max_tokens=64,
        )


def test_default_http_transport_success_and_error_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default stdlib HTTP transport maps HTTP, URL, timeout, JSON errors."""
    import urllib.request

    from rag_foundry.model_gateway.adapters import (
        ModelAdapterError,
        default_http_transport,
    )

    class _FakeResp:
        def __init__(self, body: str) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body.encode("utf-8")

        def __enter__(self) -> "_FakeResp":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _req, timeout=0: _FakeResp('{"ok": true}'),
    )
    assert default_http_transport(
        "http://localhost:11434/api/chat",
        {"model": "x"},
        {"Content-Type": "application/json"},
        5.0,
    ) == {"ok": True}

    # HTTP error
    def _raise_http(_req: Any, timeout: float = 0) -> Any:
        raise urllib.error.HTTPError(
            url="http://localhost:11434/api/chat",
            code=503,
            msg="Service Unavailable",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b"backend overloaded"),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _raise_http)
    with pytest.raises(ModelAdapterError, match="503"):
        default_http_transport("http://localhost:11434/api/chat", {}, {}, 5.0)

    # Connection error
    def _raise_url(_req: Any, timeout: float = 0) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_url)
    with pytest.raises(ModelAdapterError, match="connection refused"):
        default_http_transport("http://localhost:11434/api/chat", {}, {}, 5.0)

    # Timeout error
    def _raise_timeout(_req: Any, timeout: float = 0) -> Any:
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)
    with pytest.raises(ModelAdapterError, match="timed out"):
        default_http_transport("http://localhost:11434/api/chat", {}, {}, 5.0)

    # Invalid JSON & non-object JSON
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _req, timeout=0: _FakeResp("not-json"),
    )
    with pytest.raises(ModelAdapterError, match="invalid JSON"):
        default_http_transport("http://localhost:11434/api/chat", {}, {}, 5.0)

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _req, timeout=0: _FakeResp("[1, 2, 3]"),
    )
    with pytest.raises(ModelAdapterError, match="JSON object"):
        default_http_transport("http://localhost:11434/api/chat", {}, {}, 5.0)


def test_mock_deterministic_chat_adapter_default_and_hooks() -> None:
    """MockDeterministicChatAdapter returns reproducible JSON and hooks."""
    from rag_foundry.model_gateway.adapters import MockDeterministicChatAdapter

    profile = _mock_profile()
    msgs = (
        ChatMessage(role="system", content="Use provided evidence only."),
        ChatMessage(
            role="user",
            content="Context:\n[A1] Curated fact.\n[E1] Document passage.",
        ),
    )

    adapter = MockDeterministicChatAdapter()
    r1 = adapter.generate(
        profile, msgs, json_mode=True, temperature=0.0, max_tokens=256
    )
    r2 = adapter.generate(
        profile, msgs, json_mode=True, temperature=0.0, max_tokens=256
    )
    assert r1.content == r2.content
    assert len(adapter.calls) == 2

    parsed = json.loads(r1.content)
    assert "answer" in parsed
    assert "claims" in parsed
    assert parsed["claims"][0]["evidence_ids"] == ["A1", "E1"]
    assert r1.usage.total_tokens > 0

    # Plain-text mode returns deterministic text
    plain = adapter.generate(
        profile, msgs, json_mode=False, temperature=0.0, max_tokens=128
    )
    assert "A1" in plain.content

    # Custom responder hook takes precedence
    custom = MockDeterministicChatAdapter(
        responder=lambda prof, _m, jm: json.dumps(
            {"profile": prof.profile_id, "json_mode": jm}
        )
    )
    r_custom = custom.generate(
        profile, msgs, json_mode=True, temperature=0.0, max_tokens=128
    )
    assert json.loads(r_custom.content) == {
        "profile": "mock-qa",
        "json_mode": True,
    }
