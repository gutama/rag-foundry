"""Stdlib HTTP chat adapters and deterministic mock adapter (ADR-0006)."""

import json
import os
import re
import urllib.error
import urllib.request
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)

from pydantic import BaseModel, ConfigDict, Field

from rag_foundry.model_gateway.models import (
    ChatMessage,
    ModelAdapterError,
    ModelProfile,
    ModelProvider,
    TokenUsage,
)

HttpTransport = Callable[
    [str, Dict[str, Any], Dict[str, str], float],
    Dict[str, Any],
]

MockResponder = Callable[[ModelProfile, Sequence[ChatMessage], bool], str]

_EVIDENCE_HANDLE_RE = re.compile(r"\[([EA]\d+)\]")


class AdapterCompletionResult(BaseModel):
    """Normalized provider output returned by a ChatModelAdapter."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(description="Raw text or JSON string from provider.")
    finish_reason: Optional[str] = Field(
        default=None, description="Provider completion finish reason."
    )
    usage: TokenUsage = Field(
        default_factory=TokenUsage, description="Reported token consumption."
    )


@runtime_checkable
class ChatModelAdapter(Protocol):
    """Protocol implemented by provider-specific chat generation adapters."""

    provider: ModelProvider

    def generate(
        self,
        profile: ModelProfile,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> AdapterCompletionResult:
        """Execute a synchronous chat completion for an approved profile."""
        ...


def default_http_transport(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float,
) -> Dict[str, Any]:
    """Send a JSON HTTP POST request using Python's standard library.

    Args:
        url: Target HTTP or HTTPS endpoint URL.
        payload: JSON-serializable request dictionary.
        headers: HTTP request headers.
        timeout: Socket/request timeout in seconds.

    Returns:
        Decoded JSON response dictionary.

    Raises:
        ModelAdapterError: On HTTP, network, timeout, or JSON parsing failure.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ModelAdapterError(
            f"Chat provider HTTP error ({exc.code}): {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ModelAdapterError(
            f"Chat provider connection error: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise ModelAdapterError(
            f"Chat provider request timed out: {exc}"
        ) from exc
    except OSError as exc:
        raise ModelAdapterError(
            f"Chat provider I/O error: {exc}"
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelAdapterError(
            f"Chat provider returned invalid JSON: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ModelAdapterError(
            "Chat provider response must be a JSON object."
        )
    return parsed


def _non_negative_int(value: Any) -> int:
    """Safely coerce numeric usage fields into non-negative integers."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _build_headers(
    profile: ModelProfile,
    env: Mapping[str, str],
) -> Dict[str, str]:
    """Construct JSON HTTP headers and optional server-side Bearer token.

    Args:
        profile: Approved ModelProfile specifying optional api_key_env_var.
        env: Environment variable mapping used to resolve server-side keys.

    Returns:
        HTTP headers dictionary.

    Raises:
        ModelAdapterError: If api_key_env_var is configured but missing/empty.
    """
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if profile.api_key_env_var is not None:
        env_key = profile.api_key_env_var.strip()
        token = env.get(env_key, "").strip() if env_key else ""
        if not token:
            raise ModelAdapterError(
                f"Server-side API key environment variable '{env_key}' "
                f"is missing or empty for profile '{profile.profile_id}'."
            )
        headers["Authorization"] = f"Bearer {token}"
    return headers


class OllamaChatAdapter:
    """Stdlib HTTP chat adapter for local/private Ollama ``/api/chat``."""

    provider: ModelProvider = "ollama"

    def __init__(
        self,
        *,
        transport: Optional[HttpTransport] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        """Initialize the Ollama chat adapter.

        Args:
            transport: Optional injectable HTTP POST transport callable.
            env: Optional environment mapping for resolving API key env vars.
        """
        self._transport = transport or default_http_transport
        self._env: Mapping[str, str] = os.environ if env is None else env

    def generate(
        self,
        profile: ModelProfile,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> AdapterCompletionResult:
        """Invoke Ollama ``/api/chat`` and return a normalized completion.

        Args:
            profile: Approved Ollama ModelProfile.
            messages: Ordered chat messages.
            json_mode: Whether to request JSON output via ``format="json"``.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens (``num_predict``).

        Returns:
            AdapterCompletionResult with text content and token usage.

        Raises:
            ModelAdapterError: On provider mismatch, transport, or parse error.
        """
        if profile.provider != self.provider:
            raise ModelAdapterError(
                f"OllamaChatAdapter received mismatched provider "
                f"'{profile.provider}'."
            )
        if not profile.base_url:
            raise ModelAdapterError("Ollama profile requires a base_url.")

        options: Dict[str, Any] = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        if profile.inference_settings.top_p is not None:
            options["top_p"] = profile.inference_settings.top_p
        if profile.inference_settings.seed is not None:
            options["seed"] = profile.inference_settings.seed

        payload: Dict[str, Any] = {
            "model": profile.model_name,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages
            ],
            "stream": False,
            "options": options,
        }
        if json_mode:
            payload["format"] = "json"

        url = f"{profile.base_url.rstrip('/')}/api/chat"
        headers = _build_headers(profile, self._env)
        data = self._transport(
            url,
            payload,
            headers,
            profile.inference_settings.timeout_seconds,
        )

        message_obj = data.get("message")
        if not isinstance(message_obj, dict) or not isinstance(
            message_obj.get("content"), str
        ):
            raise ModelAdapterError(
                "Ollama response missing message content string."
            )

        prompt_tokens = _non_negative_int(data.get("prompt_eval_count"))
        completion_tokens = _non_negative_int(data.get("eval_count"))
        finish_reason = data.get("done_reason")
        if finish_reason is None and data.get("done") is True:
            finish_reason = "stop"

        return AdapterCompletionResult(
            content=message_obj["content"],
            finish_reason=(
                str(finish_reason) if finish_reason is not None else None
            ),
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )


class OpenAICompatibleChatAdapter:
    """Stdlib HTTP adapter for OpenAI-compatible ``/v1/chat/completions``."""

    provider: ModelProvider = "openai_compatible"

    def __init__(
        self,
        *,
        transport: Optional[HttpTransport] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        """Initialize the OpenAI-compatible chat adapter (e.g., vLLM).

        Args:
            transport: Optional injectable HTTP POST transport callable.
            env: Optional environment mapping for resolving API key env vars.
        """
        self._transport = transport or default_http_transport
        self._env: Mapping[str, str] = os.environ if env is None else env

    def generate(
        self,
        profile: ModelProfile,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> AdapterCompletionResult:
        """Invoke ``/v1/chat/completions`` and parse the normalized response.

        Args:
            profile: Approved OpenAI-compatible ModelProfile.
            messages: Ordered chat messages.
            json_mode: Whether to request ``response_format=json_object``.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.

        Returns:
            AdapterCompletionResult with text content and token usage.

        Raises:
            ModelAdapterError: On provider mismatch, auth, transport, or parse
                error.
        """
        if profile.provider != self.provider:
            raise ModelAdapterError(
                f"OpenAICompatibleChatAdapter received mismatched provider "
                f"'{profile.provider}'."
            )
        if not profile.base_url:
            raise ModelAdapterError(
                "OpenAI-compatible profile requires a base_url."
            )

        payload: Dict[str, Any] = {
            "model": profile.model_name,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if profile.inference_settings.top_p is not None:
            payload["top_p"] = profile.inference_settings.top_p
        if profile.inference_settings.seed is not None:
            payload["seed"] = profile.inference_settings.seed
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        base = profile.base_url.rstrip("/")
        if base.endswith("/v1"):
            url = f"{base}/chat/completions"
        else:
            url = f"{base}/v1/chat/completions"

        headers = _build_headers(profile, self._env)
        data = self._transport(
            url,
            payload,
            headers,
            profile.inference_settings.timeout_seconds,
        )

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelAdapterError(
                "OpenAI-compatible response missing non-empty choices list."
            )
        first = choices[0]
        message_obj = first.get("message") if isinstance(first, dict) else None
        if not isinstance(message_obj, dict) or not isinstance(
            message_obj.get("content"), str
        ):
            raise ModelAdapterError(
                "OpenAI-compatible response missing choices[0].message.content."
            )

        raw_usage = data.get("usage")
        usage_dict = raw_usage if isinstance(raw_usage, dict) else {}
        prompt_tokens = _non_negative_int(usage_dict.get("prompt_tokens"))
        completion_tokens = _non_negative_int(
            usage_dict.get("completion_tokens")
        )
        total_tokens = _non_negative_int(usage_dict.get("total_tokens"))
        if total_tokens == 0 and (prompt_tokens or completion_tokens):
            total_tokens = prompt_tokens + completion_tokens

        finish_reason = (
            first.get("finish_reason") if isinstance(first, dict) else None
        )
        return AdapterCompletionResult(
            content=message_obj["content"],
            finish_reason=(
                str(finish_reason) if finish_reason is not None else None
            ),
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ),
        )


class MockDeterministicChatAdapter:
    """Deterministic local mock adapter for air-gapped testing & demos."""

    provider: ModelProvider = "mock"

    def __init__(
        self,
        *,
        responder: Optional[MockResponder] = None,
        default_response: Optional[str] = None,
    ) -> None:
        """Initialize the deterministic mock chat adapter.

        Args:
            responder: Optional callback ``(profile, messages, json_mode)``
                returning raw response text.
            default_response: Optional fixed response string returned when no
                responder is provided.
        """
        self._responder = responder
        self._default_response = default_response
        self.calls: List[Tuple[str, Tuple[ChatMessage, ...], bool]] = []

    def generate(
        self,
        profile: ModelProfile,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> AdapterCompletionResult:
        """Produce deterministic mock output and record invocation trace.

        Args:
            profile: Approved mock ModelProfile.
            messages: Ordered chat messages.
            json_mode: Whether JSON structured output was requested.
            temperature: Requested sampling temperature (unused).
            max_tokens: Requested output token limit (unused).

        Returns:
            Deterministic AdapterCompletionResult.

        Raises:
            ModelAdapterError: If profile.provider is not ``"mock"``.
        """
        del temperature, max_tokens
        if profile.provider != self.provider:
            raise ModelAdapterError(
                f"MockDeterministicChatAdapter received mismatched provider "
                f"'{profile.provider}'."
            )

        msg_tuple = tuple(messages)
        self.calls.append((profile.profile_id, msg_tuple, json_mode))

        if self._responder is not None:
            content = self._responder(profile, msg_tuple, json_mode)
        elif self._default_response is not None:
            content = self._default_response
        else:
            content = self._synthesize_default(msg_tuple, json_mode=json_mode)

        prompt_tokens = sum(len(m.content.split()) for m in msg_tuple)
        completion_tokens = max(1, len(content.split()))
        return AdapterCompletionResult(
            content=content,
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    @staticmethod
    def _synthesize_default(
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool,
    ) -> str:
        """Synthesize a deterministic grounded response from prompt handles."""
        combined = "\n".join(m.content for m in messages)
        handles: List[str] = []
        for match in _EVIDENCE_HANDLE_RE.findall(combined):
            if match not in handles:
                handles.append(match)

        if not json_mode:
            if handles:
                joined = ", ".join(handles)
                return f"Grounded summary referencing evidence {joined}."
            return "Insufficient evidence provided to answer."

        if handles:
            cite_tag = " ".join(f"[{h}]" for h in handles)
            payload: Dict[str, Any] = {
                "answer": f"Grounded response based on {cite_tag}.",
                "claims": [
                    {
                        "text": (
                            "Summary supported by supplied evidence "
                            f"{cite_tag}."
                        ),
                        "evidence_ids": handles,
                    }
                ],
                "limitations": [],
                "sufficient_evidence": True,
            }
        else:
            payload = {
                "answer": "Insufficient evidence provided to answer.",
                "claims": [],
                "limitations": [
                    "No authorized evidence handles were supplied."
                ],
                "sufficient_evidence": False,
            }
        return json.dumps(payload, sort_keys=True)
