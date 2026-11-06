"""Semantic assertion domain models (ARCHITECTURE.md §8.7, ADR-0013/0014).

An assertion states that a subject entity has a property whose value is
either another entity or a literal. Extracted assertions are candidates,
not facts: they become trusted only through validation and approval.
Every assertion says where it came from (``curated`` or ``extracted``) and
which evidence chunks support it.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional, Union

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from rag_foundry.ontology.models import validate_iri

AssertionStatus = Literal[
    "candidate", "validated", "invalid", "approved", "rejected", "superseded"
]
AssertionOrigin = Literal["curated", "extracted"]
LiteralValue = Union[StrictBool, StrictInt, StrictFloat, StrictStr]


class SemanticAssertion(BaseModel):
    """A curated or extracted statement about an entity."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Id")
    workspace_id: uuid.UUID = Field(description="Owning workspace")
    semantic_profile_id: uuid.UUID = Field(description="Semantic profile")
    subject_entity_id: uuid.UUID = Field(description="Subject entity")
    property_uri: str = Field(description="Ontology property IRI")
    object_entity_id: Optional[uuid.UUID] = Field(
        default=None, description="Object entity, for object properties"
    )
    literal_value: Optional[LiteralValue] = Field(
        default=None, description="Literal value, for data properties"
    )
    source_chunk_ids: List[uuid.UUID] = Field(
        default_factory=list, description="Evidence chunks"
    )
    origin: AssertionOrigin = Field(description="curated or extracted")
    extraction_method: str = Field(
        description="How it was produced, e.g. llm, rule:x, steward"
    )
    extraction_model: Optional[str] = Field(
        default=None, description="Model used, if any"
    )
    extraction_prompt_version: Optional[str] = Field(
        default=None, description="Prompt version used, if any"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence")
    status: AssertionStatus = Field(
        default="candidate", description="Lifecycle status"
    )
    ontology_release_id: Optional[uuid.UUID] = Field(
        default=None, description="Release of the latest validation"
    )
    requires_review: bool = Field(
        default=False, description="Flagged for steward re-review"
    )
    review_reason: Optional[str] = Field(
        default=None, description="Why it was flagged"
    )
    superseded_by_id: Optional[uuid.UUID] = Field(
        default=None, description="Assertion that replaced this one"
    )
    valid_from: Optional[datetime] = Field(
        default=None, description="Start of validity (temporal)"
    )
    valid_to: Optional[datetime] = Field(
        default=None, description="End of validity (temporal)"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation time",
    )

    _check_property = field_validator("property_uri")(validate_iri)

    @field_validator("extraction_method")
    @classmethod
    def _check_method(cls, value: str) -> str:
        """Reject a blank extraction method."""
        if not value.strip():
            raise ValueError("extraction_method cannot be blank")
        return value

    @field_validator("source_chunk_ids")
    @classmethod
    def _check_evidence(cls, value: List[uuid.UUID]) -> List[uuid.UUID]:
        """Cite each chunk at most once."""
        if len(set(value)) != len(value):
            raise ValueError("Evidence chunk ids must be unique")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> "SemanticAssertion":
        """Check the value, validity interval and review flag."""
        has_object = self.object_entity_id is not None
        has_literal = self.literal_value is not None
        if has_object == has_literal:
            raise ValueError(
                "An assertion needs exactly one of object_entity_id and "
                "literal_value"
            )
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_from > self.valid_to
        ):
            raise ValueError("valid_from cannot be after valid_to")
        if self.requires_review != (self.review_reason is not None):
            raise ValueError(
                "requires_review and review_reason must be set together"
            )
        return self


class AssertionTransition(BaseModel):
    """One entry of an assertion's append-only status log."""

    id: uuid.UUID = Field(description="Entry id")
    assertion_id: uuid.UUID = Field(description="Assertion")
    sequence: int = Field(description="Position in the log, from 1")
    from_status: Optional[AssertionStatus] = Field(
        description="Previous status; None for creation"
    )
    to_status: AssertionStatus = Field(description="New status")
    actor_id: str = Field(description="Who made the change")
    reason: Optional[str] = Field(description="Why")
    created_at: datetime = Field(description="When")
