"""Strict fail-closed JSON parser for structured grounded model outputs."""

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from rag_foundry.generation.models import (
    AnswerClaim,
    ClaimAuthority,
    ParsedAnswerPayload,
)

_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)

_VALID_CLAIM_AUTHORITIES = frozenset(
    {"curated", "extracted", "document_evidence", "mixed"}
)


class AnswerParseError(ValueError):
    """Raised when raw LLM output fails strict structured JSON parsing."""


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Extract and decode a JSON object from raw or markdown-fenced output."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise AnswerParseError("Model output is empty.")

    stripped = raw_text.strip()
    candidate = stripped
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        match = _FENCED_JSON_RE.search(stripped)
        if match is None:
            raise AnswerParseError(
                "Model output is not valid JSON or a fenced JSON block."
            )
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise AnswerParseError(
                f"Fenced model output contains invalid JSON: {exc}"
            ) from exc

    if not isinstance(parsed, dict):
        raise AnswerParseError("Model output JSON must be an object.")
    return parsed


def _normalize_handle(raw_handle: Any) -> str:
    """Normalize an evidence handle string (e.g. '[E1]' -> 'E1')."""
    if not isinstance(raw_handle, str):
        raise AnswerParseError("Claim evidence_ids entries must be strings.")
    cleaned = raw_handle.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        raise AnswerParseError("Claim evidence_ids cannot contain empty IDs.")
    return cleaned


def _parse_string_list(value: Any, field_name: str) -> Tuple[str, ...]:
    """Validate an optional JSON list of non-empty strings."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AnswerParseError(f"Field '{field_name}' must be a JSON list.")
    items: List[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise AnswerParseError(
                f"Entries in '{field_name}' must be strings."
            )
        cleaned = entry.strip()
        if cleaned and cleaned not in items:
            items.append(cleaned)
    return tuple(items)


def _parse_uuid_list(value: Any, field_name: str) -> Tuple[uuid.UUID, ...]:
    """Validate an optional JSON list of UUID strings."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AnswerParseError(f"Field '{field_name}' must be a JSON list.")
    parsed_ids: List[uuid.UUID] = []
    for entry in value:
        if not isinstance(entry, str):
            raise AnswerParseError(
                f"Entries in '{field_name}' must be UUID strings."
            )
        try:
            parsed_uuid = uuid.UUID(entry.strip())
        except ValueError as exc:
            raise AnswerParseError(
                f"Invalid UUID '{entry}' in '{field_name}'."
            ) from exc
        if parsed_uuid not in parsed_ids:
            parsed_ids.append(parsed_uuid)
    return tuple(parsed_ids)


def _parse_claim(raw_claim: Any, idx: int) -> AnswerClaim:
    """Strictly parse a single claim dict into an AnswerClaim."""
    if not isinstance(raw_claim, dict):
        raise AnswerParseError(f"Claim at index {idx} must be a JSON object.")

    raw_text = raw_claim.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise AnswerParseError(
            f"Claim at index {idx} requires a non-empty 'text' string."
        )

    raw_evidence_ids = raw_claim.get("evidence_ids")
    if raw_evidence_ids is None:
        evidence_ids: Tuple[str, ...] = ()
    elif isinstance(raw_evidence_ids, list):
        deduped: List[str] = []
        for item in raw_evidence_ids:
            handle = _normalize_handle(item)
            if handle not in deduped:
                deduped.append(handle)
        evidence_ids = tuple(deduped)
    else:
        raise AnswerParseError(
            f"Claim at index {idx} field 'evidence_ids' must be a list."
        )

    concept_uris = _parse_string_list(
        raw_claim.get("concept_uris"), "concept_uris"
    )
    entity_ids = _parse_uuid_list(raw_claim.get("entity_ids"), "entity_ids")

    raw_auth = raw_claim.get("authority")
    claimed_authority: Optional[ClaimAuthority] = None
    if raw_auth is not None:
        if not isinstance(raw_auth, str):
            raise AnswerParseError(
                f"Claim at index {idx} field 'authority' must be a string."
            )
        normalized_auth = raw_auth.strip().lower()
        if normalized_auth not in _VALID_CLAIM_AUTHORITIES:
            raise AnswerParseError(
                f"Claim at index {idx} has invalid authority "
                f"'{raw_auth}'."
            )
        claimed_authority = normalized_auth  # type: ignore[assignment]

    return AnswerClaim(
        text=raw_text.strip(),
        evidence_ids=evidence_ids,
        concept_uris=concept_uris,
        entity_ids=entity_ids,
        claimed_authority=claimed_authority,
    )


def parse_model_answer(raw_text: str) -> ParsedAnswerPayload:
    """Strictly parse raw or fenced JSON model output into ParsedAnswerPayload.

    Args:
        raw_text: Raw completion content string returned by ModelGateway.

    Returns:
        Validated ParsedAnswerPayload with deterministic defaults.

    Raises:
        AnswerParseError: If output is empty, malformed JSON, or violates the
            structured grounded-answer schema.
    """
    data = _extract_json_object(raw_text)

    raw_answer = data.get("answer")
    if not isinstance(raw_answer, str) or not raw_answer.strip():
        raise AnswerParseError(
            "Model output requires a non-empty string 'answer' field."
        )

    raw_claims = data.get("claims")
    if raw_claims is None:
        claims: Tuple[AnswerClaim, ...] = ()
    elif isinstance(raw_claims, list):
        claims = tuple(
            _parse_claim(item, idx) for idx, item in enumerate(raw_claims)
        )
    else:
        raise AnswerParseError("Field 'claims' must be a JSON list.")

    limitations = _parse_string_list(data.get("limitations"), "limitations")

    raw_sufficient = data.get("sufficient_evidence", True)
    if not isinstance(raw_sufficient, bool):
        raise AnswerParseError(
            "Field 'sufficient_evidence' must be a JSON boolean."
        )

    return ParsedAnswerPayload(
        answer=raw_answer.strip(),
        claims=claims,
        limitations=limitations,
        sufficient_evidence=raw_sufficient,
    )
