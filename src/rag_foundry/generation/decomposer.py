"""Bounded multi-step question decomposition with deterministic fallback."""

import json
import re
from typing import List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from rag_foundry.generation.prompts import build_decomposition_messages
from rag_foundry.model_gateway.gateway import ModelGateway
from rag_foundry.model_gateway.models import ChatGenerationRequest

_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)

_INTERROGATIVE_CONJ_RE = re.compile(
    r"\s+(?:and\s+also|as\s+well\s+as|and\s+(?=(?:what|how|who|when|where|"
    r"why|which|does|do|is|are|can|should|must)\b))\s*",
    re.IGNORECASE,
)

_COMPARE_SPLIT_RE = re.compile(
    r"\s+(?:versus|vs\.?|compared\s+(?:to|with))\s+",
    re.IGNORECASE,
)


class DecompositionResult(BaseModel):
    """Structured output of QueryDecomposer with execution provenance."""

    model_config = ConfigDict(frozen=True)

    original_question: str = Field(description="Original complex question.")
    sub_questions: Tuple[str, ...] = Field(
        min_length=1, description="Bounded, deduplicated sub-questions."
    )
    method: Literal["llm", "deterministic_fallback"] = Field(
        description="Whether LLM decomposition or fallback splitter was used."
    )
    model_profile_id: Optional[str] = Field(
        default=None, description="Executed decomposition profile ID, if any."
    )


def _clean_and_dedupe(
    candidates: Sequence[str],
    max_sub_questions: int,
) -> Tuple[str, ...]:
    """Normalize, deduplicate case-insensitively, and cap sub-questions."""
    seen: set[str] = set()
    cleaned: List[str] = []
    for raw in candidates:
        item = " ".join(str(raw).strip().split())
        item = item.lstrip("-*0123456789.) ").strip()
        if not item:
            continue
        key = item.lower().rstrip("?.!")
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
        if len(cleaned) >= max_sub_questions:
            break
    return tuple(cleaned)


def deterministic_split_question(
    question: str,
    *,
    max_sub_questions: int = 4,
) -> Tuple[str, ...]:
    """Deterministically split a multi-part question into bounded sub-queries.

    Args:
        question: User's input question string.
        max_sub_questions: Maximum number of sub-questions to emit.

    Returns:
        Non-empty tuple of deduplicated sub-questions capped at
        ``max_sub_questions``.
    """
    if max_sub_questions < 1:
        raise ValueError("max_sub_questions must be >= 1.")

    stripped = " ".join(question.strip().split())
    if not stripped:
        raise ValueError("Question must be non-empty.")

    # 1. Explicit question-mark / semicolon / newline delimiters.
    if "?" in stripped[:-1] or ";" in stripped or "\n" in question:
        raw_parts = re.split(r"(?<=\?)\s+|;\s*|\n+", question.strip())
        parts = _clean_and_dedupe(raw_parts, max_sub_questions)
        if len(parts) >= 2:
            return parts

    # 2. Compound interrogative conjunctions (e.g. "What is X and how is Y?").
    conj_parts = _INTERROGATIVE_CONJ_RE.split(stripped)
    if len(conj_parts) >= 2:
        suffix = "?" if stripped.endswith("?") else ""
        normalized = [
            p.rstrip(", ") + ("" if p.endswith("?") else suffix)
            for p in conj_parts
        ]
        parts = _clean_and_dedupe(normalized, max_sub_questions)
        if len(parts) >= 2:
            return parts

    # 3. Explicit comparison phrases ("X vs Y", "X compared to Y").
    cmp_parts = _COMPARE_SPLIT_RE.split(stripped)
    if len(cmp_parts) >= 2:
        parts = _clean_and_dedupe(cmp_parts, max_sub_questions)
        if len(parts) >= 2:
            return parts

    return (stripped,)


def _parse_sub_questions_json(raw_text: str) -> Optional[List[str]]:
    """Parse strict JSON {"sub_questions": [...]} from raw or fenced text."""
    stripped = raw_text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = _FENCED_JSON_RE.search(stripped)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    if not isinstance(parsed, dict):
        return None
    raw_list = parsed.get("sub_questions")
    if not isinstance(raw_list, list):
        return None
    strings = [s for s in raw_list if isinstance(s, str) and s.strip()]
    return strings if strings else None


class QueryDecomposer:
    """Decomposes complex questions via ModelGateway or deterministic fallback.

    When an explicit ``profile_id`` is provided, ``ModelGateway`` policy checks
    execute fail-closed (unknown, unapproved, or task-mismatched profiles raise
    their typed errors rather than silently falling back). If the approved
    model returns malformed JSON, decomposition falls back safely to
    ``deterministic_split_question``.
    """

    def __init__(
        self,
        model_gateway: Optional[ModelGateway] = None,
    ) -> None:
        """Initialize QueryDecomposer.

        Args:
            model_gateway: Optional ModelGateway for LLM-assisted splitting.
        """
        self._gateway = model_gateway

    async def decompose(
        self,
        question: str,
        *,
        max_sub_questions: int = 4,
        profile_id: Optional[str] = None,
        profile_version: Optional[str] = None,
    ) -> DecompositionResult:
        """Split a complex question into bounded, deduplicated sub-questions.

        Args:
            question: Original complex user question.
            max_sub_questions: Hard upper bound on sub-questions emitted.
            profile_id: Optional approved ``query_decomposition`` profile ID.
            profile_version: Optional explicit version for ``profile_id``.

        Returns:
            DecompositionResult recording sub-questions and method provenance.

        Raises:
            ModelProfileNotFoundError: If ``profile_id`` does not exist.
            ModelProfilePolicyError: If ``profile_id`` fails ADR-0006 policy.
        """
        cleaned_q = question.strip()
        if max_sub_questions < 1:
            raise ValueError("max_sub_questions must be >= 1.")

        if self._gateway is not None and profile_id is not None:
            # Fail closed on profile resolution / task / network policy!
            resolved = self._gateway.resolve_profile(
                profile_id,
                version=profile_version,
                task="query_decomposition",
            )
            messages = build_decomposition_messages(
                cleaned_q, max_sub_questions=max_sub_questions
            )
            resp = await self._gateway.generate(
                ChatGenerationRequest(
                    profile_id=resolved.profile_id,
                    profile_version=resolved.version,
                    task="query_decomposition",
                    messages=messages,
                    json_mode=True,
                )
            )
            parsed = _parse_sub_questions_json(resp.content)
            if parsed:
                deduped = _clean_and_dedupe(parsed, max_sub_questions)
                if deduped:
                    return DecompositionResult(
                        original_question=cleaned_q,
                        sub_questions=deduped,
                        method="llm",
                        model_profile_id=resolved.profile_id,
                    )

        fallback_parts = deterministic_split_question(
            cleaned_q, max_sub_questions=max_sub_questions
        )
        return DecompositionResult(
            original_question=cleaned_q,
            sub_questions=fallback_parts,
            method="deterministic_fallback",
            model_profile_id=None,
        )
