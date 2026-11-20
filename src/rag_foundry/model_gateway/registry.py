"""Protocol and in-memory registry for versioned ModelProfile governance."""

import re
from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable

from rag_foundry.model_gateway.models import (
    DuplicateModelProfileError,
    InferenceSettings,
    ModelProfile,
    ModelProfileNotFoundError,
    ModelProfileStatus,
    ModelTask,
)

_SEMVER_PART_RE = re.compile(r"\d+")


def _version_sort_key(version: str) -> Tuple[Tuple[int, ...], str]:
    """Build a deterministic descending-friendly sort key for version strings.

    Args:
        version: Profile version string (e.g. ``"1.10.0"``).

    Returns:
        Tuple combining parsed integer components and raw string tie-breaker.
    """
    nums = tuple(int(part) for part in _SEMVER_PART_RE.findall(version))
    return (nums, version)


@runtime_checkable
class ModelProfileRepository(Protocol):
    """Repository protocol for approved, versioned model profiles (ADR-0006)."""

    def register(self, profile: ModelProfile) -> ModelProfile:
        """Register a new versioned ModelProfile."""
        ...

    def get(
        self,
        profile_id: str,
        version: Optional[str] = None,
    ) -> Optional[ModelProfile]:
        """Resolve a profile by ID and optional exact version."""
        ...

    def list_profiles(
        self,
        *,
        task: Optional[ModelTask] = None,
        status: Optional[ModelProfileStatus] = None,
    ) -> List[ModelProfile]:
        """List registered profiles filtered by optional task and status."""
        ...

    def approve(self, profile_id: str, version: str) -> ModelProfile:
        """Transition a registered profile version to ``approved``."""
        ...

    def deprecate(self, profile_id: str, version: str) -> ModelProfile:
        """Transition a registered profile version to ``deprecated``."""
        ...


class InMemoryModelProfileRegistry:
    """In-memory, config-backed implementation of ModelProfileRepository.

    Keys profiles by ``(profile_id, version)``. Unversioned lookups prefer the
    highest-version ``approved`` profile and fall back to the highest-version
    registered profile so callers can distinguish missing vs. unapproved state.
    """

    def __init__(
        self,
        profiles: Optional[List[ModelProfile]] = None,
    ) -> None:
        """Initialize an in-memory registry with optional initial profiles.

        Args:
            profiles: Optional list of ModelProfile entries to register.
        """
        self._profiles: Dict[Tuple[str, str], ModelProfile] = {}
        if profiles:
            for profile in profiles:
                self.register(profile)

    def register(self, profile: ModelProfile) -> ModelProfile:
        """Register a unique ``(profile_id, version)`` profile.

        Args:
            profile: Validated ModelProfile to store.

        Returns:
            Stored ModelProfile instance.

        Raises:
            DuplicateModelProfileError: If ``(profile_id, version)`` exists.
        """
        key = (profile.profile_id, profile.version)
        if key in self._profiles:
            raise DuplicateModelProfileError(
                f"Model profile '{profile.profile_id}' version "
                f"'{profile.version}' is already registered."
            )
        self._profiles[key] = profile
        return profile

    def get(
        self,
        profile_id: str,
        version: Optional[str] = None,
    ) -> Optional[ModelProfile]:
        """Look up a profile by ID and optional explicit version.

        Args:
            profile_id: Target profile identifier.
            version: Optional explicit version string.

        Returns:
            Matching ModelProfile, or ``None`` if not registered.
        """
        cleaned_id = profile_id.strip()
        if version is not None:
            return self._profiles.get((cleaned_id, version.strip()))

        candidates = [
            prof
            for (pid, _), prof in self._profiles.items()
            if pid == cleaned_id
        ]
        if not candidates:
            return None

        approved = [p for p in candidates if p.status == "approved"]
        pool = approved if approved else candidates
        pool.sort(key=lambda p: _version_sort_key(p.version), reverse=True)
        return pool[0]

    def list_profiles(
        self,
        *,
        task: Optional[ModelTask] = None,
        status: Optional[ModelProfileStatus] = None,
    ) -> List[ModelProfile]:
        """Return deterministically ordered registered profiles.

        Args:
            task: Optional ModelTask filter.
            status: Optional ModelProfileStatus filter.

        Returns:
            Sorted list of matching ModelProfile objects.
        """
        matches = [
            prof
            for prof in self._profiles.values()
            if (task is None or prof.task == task)
            and (status is None or prof.status == status)
        ]
        matches.sort(
            key=lambda p: (p.profile_id, _version_sort_key(p.version))
        )
        return matches

    def approve(self, profile_id: str, version: str) -> ModelProfile:
        """Mark a registered profile version as ``approved``.

        Args:
            profile_id: Target profile identifier.
            version: Registered version string.

        Returns:
            Updated ModelProfile with ``status="approved"``.

        Raises:
            ModelProfileNotFoundError: If ``(profile_id, version)`` is missing.
        """
        key = (profile_id.strip(), version.strip())
        existing = self._profiles.get(key)
        if existing is None:
            raise ModelProfileNotFoundError(
                f"Model profile '{profile_id}' version '{version}' not found."
            )
        updated = existing.model_copy(update={"status": "approved"})
        self._profiles[key] = updated
        return updated

    def deprecate(self, profile_id: str, version: str) -> ModelProfile:
        """Mark a registered profile version as ``deprecated``.

        Args:
            profile_id: Target profile identifier.
            version: Registered version string.

        Returns:
            Updated ModelProfile with ``status="deprecated"``.

        Raises:
            ModelProfileNotFoundError: If ``(profile_id, version)`` is missing.
        """
        key = (profile_id.strip(), version.strip())
        existing = self._profiles.get(key)
        if existing is None:
            raise ModelProfileNotFoundError(
                f"Model profile '{profile_id}' version '{version}' not found."
            )
        updated = existing.model_copy(update={"status": "deprecated"})
        self._profiles[key] = updated
        return updated

    @classmethod
    def with_local_defaults(
        cls,
        *,
        ollama_base_url: str = "http://localhost:11434",
        vllm_base_url: str = "http://localhost:8000",
    ) -> "InMemoryModelProfileRegistry":
        """Create a registry seeded with approved local-only default profiles.

        Args:
            ollama_base_url: Local Ollama server base URL.
            vllm_base_url: Local OpenAI-compatible vLLM server base URL.

        Returns:
            Pre-populated InMemoryModelProfileRegistry.
        """
        defaults = [
            ModelProfile(
                profile_id="fast-local",
                version="1.0.0",
                task="chat_generation",
                provider="ollama",
                model_name="llama3.2:3b",
                base_url=ollama_base_url,
                deployment_policy="local_only",
                data_handling_class="restricted",
                status="approved",
                inference_settings=InferenceSettings(
                    temperature=0.0, max_tokens=1024, json_mode=True
                ),
                description="Fast local Ollama profile for low-latency QA.",
            ),
            ModelProfile(
                profile_id="balanced-local",
                version="1.0.0",
                task="chat_generation",
                provider="ollama",
                model_name="llama3.1:8b",
                base_url=ollama_base_url,
                deployment_policy="local_only",
                data_handling_class="restricted",
                status="approved",
                inference_settings=InferenceSettings(
                    temperature=0.0, max_tokens=2048, json_mode=True
                ),
                description="Balanced local Ollama profile for grounded QA.",
            ),
            ModelProfile(
                profile_id="high-accuracy-private",
                version="1.0.0",
                task="chat_generation",
                provider="openai_compatible",
                model_name="qwen2.5:32b-instruct",
                base_url=vllm_base_url,
                deployment_policy="local_only",
                data_handling_class="restricted",
                status="approved",
                inference_settings=InferenceSettings(
                    temperature=0.0, max_tokens=4096, json_mode=True
                ),
                description="High-accuracy private vLLM profile.",
            ),
            ModelProfile(
                profile_id="query-decomposer-local",
                version="1.0.0",
                task="query_decomposition",
                provider="ollama",
                model_name="llama3.2:3b",
                base_url=ollama_base_url,
                deployment_policy="local_only",
                data_handling_class="restricted",
                status="approved",
                inference_settings=InferenceSettings(
                    temperature=0.0, max_tokens=512, json_mode=True
                ),
                description="Local profile for multi-step QA decomposition.",
            ),
        ]
        return cls(profiles=defaults)
