"""Entity and mention domain models (ADR-0012, ARCHITECTURE.md §8.6).

Entity resolution separates surface **mentions** from authoritative
**entities**. An entity has a stable internal id that never changes; its
canonical IRI, labels, aliases and typed external identifiers are
attributes, not interchangeable keys. A mention records where a name was
found and how far its resolution has progressed.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from rag_foundry.ontology.models import (
    validate_iri,
    validate_labels,
    validate_language_tag,
)

EntityStatus = Literal["active", "merged", "split", "deprecated"]
ResolutionStatus = Literal["unresolved", "candidate", "resolved"]

# Identifier schemes are short lowercase tokens such as "lei", "swift_bic"
# or "id.npwp".
_SCHEME_PATTERN = re.compile(r"^[a-z][a-z0-9_.\-]{0,63}$")
MAX_IDENTIFIER_LENGTH = 256


def validate_identifiers(identifiers: Dict[str, str]) -> Dict[str, str]:
    """Check a map of identifier scheme to value.

    Args:
        identifiers: Scheme to identifier value.

    Returns:
        The unchanged map.

    Raises:
        ValueError: If a scheme is not a lowercase token, or a value is
            blank, padded with whitespace or too long.
    """
    for scheme, value in identifiers.items():
        if not _SCHEME_PATTERN.match(scheme):
            raise ValueError(
                f"Identifier scheme {scheme!r} must be a lowercase token"
            )
        if not value.strip() or value != value.strip():
            raise ValueError(
                f"The {scheme} identifier must be non-blank and trimmed"
            )
        if len(value) > MAX_IDENTIFIER_LENGTH:
            raise ValueError(f"The {scheme} identifier is too long")
    return identifiers


def validate_aliases(aliases: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Check a map of language tag to alias list.

    Args:
        aliases: Language tag to aliases.

    Returns:
        The unchanged map.

    Raises:
        ValueError: If a tag is not BCP 47, or an alias is blank or
            repeated within its language.
    """
    for language, names in aliases.items():
        validate_language_tag(language)
        if any(not name.strip() for name in names):
            raise ValueError(f"Aliases in {language!r} cannot be blank")
        if len(set(names)) != len(names):
            raise ValueError(f"Aliases in {language!r} must be unique")
    return aliases


class Entity(BaseModel):
    """An authoritative entity with a stable internal identity."""

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="Stable internal id"
    )
    workspace_id: uuid.UUID = Field(description="Owning workspace")
    semantic_profile_id: uuid.UUID = Field(description="Semantic profile")
    canonical_uri: str = Field(description="Canonical entity IRI")
    ontology_class_uri: str = Field(description="Ontology class IRI")
    preferred_labels: Dict[str, str] = Field(
        description="Language tag to preferred label"
    )
    aliases: Dict[str, List[str]] = Field(
        default_factory=dict, description="Language tag to aliases"
    )
    identifiers: Dict[str, str] = Field(
        default_factory=dict,
        description="Typed authoritative identifiers: scheme to value",
    )
    status: EntityStatus = Field(default="active", description="Status")
    merged_into_id: Optional[uuid.UUID] = Field(
        default=None, description="Survivor this entity was merged into"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )

    _check_canonical = field_validator("canonical_uri")(validate_iri)
    _check_class = field_validator("ontology_class_uri")(validate_iri)
    _check_labels = field_validator("preferred_labels")(validate_labels)
    _check_aliases = field_validator("aliases")(validate_aliases)
    _check_identifiers = field_validator("identifiers")(validate_identifiers)

    @model_validator(mode="after")
    def _check_redirect(self) -> "Entity":
        """Keep the merged status and its redirect consistent."""
        if (self.status == "merged") != (self.merged_into_id is not None):
            raise ValueError(
                "A merged entity needs merged_into_id, and only a merged "
                "entity may have one"
            )
        if self.merged_into_id == self.id:
            raise ValueError("An entity cannot be merged into itself")
        return self

    def all_labels(self) -> List[str]:
        """List preferred labels, then aliases, each text once.

        Returns:
            Distinct label texts in a stable order.
        """
        names = list(self.preferred_labels.values())
        for language_aliases in self.aliases.values():
            names.extend(language_aliases)
        return list(dict.fromkeys(names))


class Mention(BaseModel):
    """A surface mention of an entity found in a source chunk."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Id")
    workspace_id: uuid.UUID = Field(description="Owning workspace")
    semantic_profile_id: uuid.UUID = Field(description="Semantic profile")
    chunk_id: uuid.UUID = Field(description="Chunk the mention occurs in")
    start_offset: int = Field(ge=0, description="Span start (characters)")
    end_offset: int = Field(description="Span end, exclusive")
    surface_text: str = Field(description="Text as it appears")
    ontology_class_uri: Optional[str] = Field(
        default=None, description="Expected ontology class, if known"
    )
    identifiers: Dict[str, str] = Field(
        default_factory=dict,
        description="Identifiers extracted alongside the mention",
    )
    resolution_status: ResolutionStatus = Field(
        default="unresolved", description="Resolution progress"
    )
    resolved_entity_id: Optional[uuid.UUID] = Field(
        default=None, description="Entity the mention resolved to"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )

    _check_identifiers = field_validator("identifiers")(validate_identifiers)

    @field_validator("surface_text")
    @classmethod
    def _check_text(cls, text: str) -> str:
        """Reject blank surface text."""
        if not text.strip():
            raise ValueError("Surface text cannot be blank")
        return text

    @field_validator("ontology_class_uri")
    @classmethod
    def _check_class(cls, value: Optional[str]) -> Optional[str]:
        """Validate the class hint when present."""
        return None if value is None else validate_iri(value)

    @model_validator(mode="after")
    def _check_consistency(self) -> "Mention":
        """Check the span and the resolution link."""
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        resolved = self.resolution_status == "resolved"
        if resolved != (self.resolved_entity_id is not None):
            raise ValueError(
                "A resolved mention needs resolved_entity_id, and only a "
                "resolved mention may have one"
            )
        return self
