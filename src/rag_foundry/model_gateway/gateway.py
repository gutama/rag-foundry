"""Fail-closed ModelGateway enforcing ADR-0006 profiles and air-gap policy."""

import asyncio
import ipaddress
import re
import time
from typing import Collection, Dict, Mapping, Optional, Set
from urllib.parse import urlparse

from rag_foundry.model_gateway.adapters import (
    ChatModelAdapter,
    MockDeterministicChatAdapter,
    OllamaChatAdapter,
    OpenAICompatibleChatAdapter,
)
from rag_foundry.model_gateway.models import (
    ChatGenerationRequest,
    ChatGenerationResponse,
    ModelProfile,
    ModelProfileNotFoundError,
    ModelProfilePolicyError,
    ModelProvider,
    ModelTask,
)
from rag_foundry.model_gateway.registry import ModelProfileRepository

_LOCAL_HOSTNAMES = frozenset({"localhost", "host.docker.internal"})
_LOCAL_SUFFIXES = (".local", ".internal", ".localhost")
_SINGLE_LABEL_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_HEX_LITERAL_RE = re.compile(r"^0x[0-9a-f]+$")


def is_local_or_private_host(url: str) -> bool:
    """Return True iff the HTTP(S) URL targets a local/private network host.

    Permits loopback, RFC1918/ULA private IPs, link-local addresses,
    ``localhost``, ``host.docker.internal``, ``*.local``/``*.internal``
    domains, and non-numeric single-label cluster service names (such as
    ``ollama`` or ``vllm``). Rejects public IPs, public internet domains,
    unspecified addresses (``0.0.0.0``), and integer/hex IP literals.

    Args:
        url: HTTP or HTTPS URL string to inspect.

    Returns:
        True if the URL host stays within local/private boundaries.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False

    host = parsed.hostname.lower().rstrip(".")
    if not host:
        return False

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if ip.is_unspecified or ip.is_multicast:
            return False
        return bool(ip.is_loopback or ip.is_private or ip.is_link_local)

    if host in _LOCAL_HOSTNAMES or host.endswith(_LOCAL_SUFFIXES):
        return True

    if "." not in host and _SINGLE_LABEL_HOST_RE.match(host):
        if host.isdigit() or _HEX_LITERAL_RE.match(host):
            return False
        return True

    return False


class ModelGateway:
    """Fail-closed gateway executing only approved server-governed profiles.

    Enforces ADR-0006 invariants before any provider call:
    - Unknown profile IDs/versions fail with ``ModelProfileNotFoundError``.
    - ``draft`` or ``deprecated`` profiles fail with
      ``ModelProfilePolicyError``.
    - Task mismatches fail with ``ModelProfilePolicyError``.
    - ``local_only`` profiles reject public/non-local endpoints and never
      fall back silently to remote providers.
    - ``approved_remote`` endpoints remain blocked unless explicitly enabled
      via ``allow_approved_remote=True`` (and optionally host-allowlisted).
    - Blocking HTTP adapters are offloaded via ``asyncio.to_thread``.
    """

    def __init__(
        self,
        registry: ModelProfileRepository,
        *,
        adapters: Optional[Mapping[ModelProvider, ChatModelAdapter]] = None,
        allow_approved_remote: bool = False,
        allowed_remote_hosts: Optional[Collection[str]] = None,
    ) -> None:
        """Initialize ModelGateway with a profile registry and adapters.

        Args:
            registry: ModelProfileRepository holding versioned profiles.
            adapters: Optional explicit mapping of provider -> adapter. When
                omitted, registers default Ollama, OpenAI-compatible, and mock
                adapters.
            allow_approved_remote: Whether ``approved_remote`` profiles may
                contact non-local hosts. Defaults to False (air-gapped safe).
            allowed_remote_hosts: Optional explicit set of permitted remote
                hostnames when ``allow_approved_remote`` is True.
        """
        self._registry = registry
        if adapters is None:
            self._adapters: Dict[ModelProvider, ChatModelAdapter] = {
                "ollama": OllamaChatAdapter(),
                "openai_compatible": OpenAICompatibleChatAdapter(),
                "mock": MockDeterministicChatAdapter(),
            }
        else:
            self._adapters = dict(adapters)
        self._allow_approved_remote = allow_approved_remote
        self._allowed_remote_hosts: Optional[Set[str]] = (
            {h.strip().lower().rstrip(".") for h in allowed_remote_hosts}
            if allowed_remote_hosts is not None
            else None
        )

    def resolve_profile(
        self,
        profile_id: str,
        *,
        version: Optional[str] = None,
        task: ModelTask = "chat_generation",
    ) -> ModelProfile:
        """Resolve and policy-validate an approved profile before execution.

        Args:
            profile_id: Requested server-controlled profile ID.
            version: Optional explicit profile version.
            task: Expected workload category.

        Returns:
            Approved, policy-validated ModelProfile.

        Raises:
            ModelProfileNotFoundError: If the profile or version is missing.
            ModelProfilePolicyError: If status, task, network boundary, or
                registered adapter fails policy validation.
        """
        profile = self._registry.get(profile_id, version=version)
        if profile is None:
            ver_desc = f" version '{version}'" if version is not None else ""
            raise ModelProfileNotFoundError(
                f"Model profile '{profile_id}'{ver_desc} was not found."
            )

        if profile.status != "approved":
            raise ModelProfilePolicyError(
                f"Model profile '{profile.profile_id}' version "
                f"'{profile.version}' has status '{profile.status}' and "
                "cannot be executed (must be 'approved')."
            )

        if profile.task != task:
            raise ModelProfilePolicyError(
                f"Model profile '{profile.profile_id}' is registered for "
                f"task '{profile.task}', not requested task '{task}'."
            )

        self._validate_deployment_policy(profile)

        if profile.provider not in self._adapters:
            raise ModelProfilePolicyError(
                f"No chat adapter is registered for provider "
                f"'{profile.provider}' (no fallback permitted)."
            )

        return profile

    def _validate_deployment_policy(self, profile: ModelProfile) -> None:
        """Enforce local_only and approved_remote host boundaries."""
        if profile.provider == "mock":
            return

        if not profile.base_url:
            raise ModelProfilePolicyError(
                f"HTTP profile '{profile.profile_id}' is missing base_url."
            )

        is_local = is_local_or_private_host(profile.base_url)
        if profile.deployment_policy == "local_only":
            if not is_local:
                raise ModelProfilePolicyError(
                    f"Profile '{profile.profile_id}' enforces 'local_only' "
                    f"deployment policy and forbids non-local URL "
                    f"'{profile.base_url}'."
                )
            return

        # deployment_policy == "approved_remote"
        if not is_local:
            if not self._allow_approved_remote:
                raise ModelProfilePolicyError(
                    f"Profile '{profile.profile_id}' targets remote URL "
                    f"'{profile.base_url}', but gateway remote routing is "
                    "disabled."
                )
            parsed = urlparse(profile.base_url)
            host = (parsed.hostname or "").lower().rstrip(".")
            if (
                self._allowed_remote_hosts is not None
                and host not in self._allowed_remote_hosts
            ):
                raise ModelProfilePolicyError(
                    f"Remote host '{host}' for profile "
                    f"'{profile.profile_id}' is not in the gateway remote "
                    "host allowlist."
                )

    async def generate(
        self,
        request: ChatGenerationRequest,
    ) -> ChatGenerationResponse:
        """Execute a governed chat generation call without blocking asyncio.

        Args:
            request: Validated ChatGenerationRequest referencing an approved
                profile ID.

        Returns:
            ChatGenerationResponse containing generated text and full model
            reproducibility trace metadata.

        Raises:
            ModelProfileNotFoundError: If the requested profile does not exist.
            ModelProfilePolicyError: If any governance policy check fails.
            ModelAdapterError: If the underlying adapter fails.
        """
        profile = self.resolve_profile(
            request.profile_id,
            version=request.profile_version,
            task=request.task,
        )
        adapter = self._adapters[profile.provider]

        effective_json_mode = (
            profile.inference_settings.json_mode
            if request.json_mode is None
            else request.json_mode
        )
        effective_temperature = (
            profile.inference_settings.temperature
            if request.temperature is None
            else request.temperature
        )
        effective_max_tokens = (
            profile.inference_settings.max_tokens
            if request.max_tokens is None
            else request.max_tokens
        )

        start = time.perf_counter()
        result = await asyncio.to_thread(
            adapter.generate,
            profile,
            request.messages,
            json_mode=effective_json_mode,
            temperature=effective_temperature,
            max_tokens=effective_max_tokens,
        )
        duration_ms = round((time.perf_counter() - start) * 1000.0, 3)

        return ChatGenerationResponse(
            content=result.content,
            profile_id=profile.profile_id,
            profile_version=profile.version,
            provider=profile.provider,
            model_name=profile.model_name,
            model_revision=profile.model_revision,
            finish_reason=result.finish_reason,
            usage=result.usage,
            duration_ms=duration_ms,
        )
