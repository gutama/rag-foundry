"""SKOS taxonomy domain models and concept schemes."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class SKOSConceptModel(BaseModel):
    """SKOS Concept domain representation."""

    concept_id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="Unique concept UUID"
    )
    scheme_uri: str = Field(description="Parent SKOS concept scheme URI")
    uri: str = Field(description="Unique SKOS concept URI")
    pref_label: str = Field(description="Preferred human-readable label")
    alt_labels: List[str] = Field(
        default_factory=list, description="Alternative labels and synonyms"
    )
    hidden_labels: List[str] = Field(
        default_factory=list, description="Hidden labels for indexing"
    )
    broader_uris: List[str] = Field(
        default_factory=list, description="Broader parent concept URIs"
    )
    narrower_uris: List[str] = Field(
        default_factory=list, description="Narrower child concept URIs"
    )
    related_uris: List[str] = Field(
        default_factory=list, description="Related concept URIs"
    )
    is_deprecated: bool = Field(
        default=False, description="True if concept is deprecated"
    )
    deprecation_note: Optional[str] = Field(
        default=None, description="Deprecation reason or note"
    )


class SKOSConceptSchemeModel(BaseModel):
    """SKOS Concept Scheme container."""

    scheme_id: str = Field(description="Unique scheme string identifier")
    uri: str = Field(description="Unique SKOS concept scheme URI")
    title: str = Field(description="Human-readable scheme title")
    description: Optional[str] = Field(
        default=None, description="Scheme description"
    )
    version: str = Field(default="1.0.0", description="Scheme version string")
    concepts: List[SKOSConceptModel] = Field(
        default_factory=list, description="Concepts contained in scheme"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Scheme creation timestamp",
    )
