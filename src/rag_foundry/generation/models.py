"""Structured answer, claim, and evidence provenance models (ADR-0013)."""

import uuid
from enum import Enum
from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from rag_foundry.retrieval.models import BoundingBox


class KnowledgeAuthority(str, Enum):
    """Explicit authority class distinguishing curated vs. extracted context."""

    CURATED = "curated"
    EXTRACTED = "extracted"
    DOCUMENT_EVIDENCE = "document_evidence"


ClaimAuthority = Literal[
    "curated",
    "extracted",
    "document_evidence",
    "mixed",
]

QAMode = Literal["standard", "curated_knowledge", "decomposed"]


class EvidenceEntry(BaseModel):
    """Normalized, authorized evidence item with a deterministic handle."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(
        description="Deterministic citation handle (e.g. 'E1' or 'A1')."
    )
    authority: KnowledgeAuthority = Field(
        description="Explicit authority class (ADR-0013)."
    )
    text: str = Field(
        min_length=1, description="Formatted passage or assertion text."
    )
    workspace_id: uuid.UUID = Field(description="Owning workspace ID.")
    security_domain: str = Field(
        description="Primary security domain tag for authorization checks."
    )
    security_domains: Tuple[str, ...] = Field(
        default=(),
        description=(
            "All security domains required to view this evidence item."
        ),
    )
    document_version_id: Optional[uuid.UUID] = Field(
        default=None, description="Canonical source document version ID."
    )
    document_title: Optional[str] = Field(
        default=None, description="Human-readable source document title."
    )
    chunk_id: Optional[uuid.UUID] = Field(
        default=None, description="Primary source chunk ID."
    )
    source_chunk_ids: Tuple[uuid.UUID, ...] = Field(
        default=(),
        description="All backing chunk IDs (for assertions or merged spans).",
    )
    assertion_id: Optional[uuid.UUID] = Field(
        default=None, description="Backing AssertionRecord ID when applicable."
    )
    assertion_origin: Optional[Literal["curated", "extracted"]] = Field(
        default=None, description="Original assertion origin field."
    )
    assertion_status: Optional[str] = Field(
        default=None, description="Lifecycle status of backing assertion."
    )
    subject_entity_id: Optional[uuid.UUID] = Field(
        default=None, description="Subject entity ID for semantic assertions."
    )
    object_entity_id: Optional[uuid.UUID] = Field(
        default=None, description="Object entity ID for semantic assertions."
    )
    property_uri: Optional[str] = Field(
        default=None, description="Ontology property URI for assertions."
    )
    section_path: Tuple[str, ...] = Field(
        default=(), description="Hierarchical source document section path."
    )
    page_numbers: Tuple[int, ...] = Field(
        default=(), description="1-indexed source page numbers."
    )
    bounding_boxes: Tuple[BoundingBox, ...] = Field(
        default=(), description="Normalized page bounding boxes."
    )
    concept_uris: Tuple[str, ...] = Field(
        default=(), description="Linked SKOS/ontology concept URIs."
    )
    entity_ids: Tuple[uuid.UUID, ...] = Field(
        default=(), description="Linked canonical entity UUIDs."
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Retrieval relevance or assertion confidence score.",
    )

    @field_validator("evidence_id", "security_domain")
    @classmethod
    def _validate_non_empty_strings(cls, value: str) -> str:
        """Ensure handle and security domain strings are non-empty."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Identifier fields must be non-empty.")
        return cleaned

    @model_validator(mode="after")
    def _normalize_domains_and_chunks(self) -> "EvidenceEntry":
        """Ensure security_domains always includes primary security_domain."""
        domains = list(self.security_domains)
        if self.security_domain not in domains:
            domains.insert(0, self.security_domain)
        deduped_domains = tuple(
            dict.fromkeys(d.strip() for d in domains if d.strip())
        )
        object.__setattr__(self, "security_domains", deduped_domains)

        if (
            self.chunk_id is not None
            and self.chunk_id not in self.source_chunk_ids
        ):
            chunks = (self.chunk_id, *self.source_chunk_ids)
            object.__setattr__(self, "source_chunk_ids", chunks)
        return self


class AnswerClaim(BaseModel):
    """Single factual claim linked to cited evidence handles."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, description="Claim statement text.")
    evidence_ids: Tuple[str, ...] = Field(
        default=(), description="Cited evidence handles (e.g. 'E1', 'A1')."
    )
    concept_uris: Tuple[str, ...] = Field(
        default=(), description="Relevant taxonomy or ontology concept URIs."
    )
    entity_ids: Tuple[uuid.UUID, ...] = Field(
        default=(), description="Relevant canonical entity UUIDs."
    )
    authority: Optional[ClaimAuthority] = Field(
        default=None,
        description="Effective claim authority derived from cited evidence.",
    )
    claimed_authority: Optional[ClaimAuthority] = Field(
        default=None,
        description="Optional authority self-reported by the language model.",
    )
    support_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Post-generation claim-to-passage support alignment score.",
    )
    verified: bool = Field(
        default=False,
        description="True iff all citations and alignment checks passed.",
    )


class ParsedAnswerPayload(BaseModel):
    """Structured model output parsed strictly before citation validation."""

    model_config = ConfigDict(frozen=True)

    answer: str = Field(min_length=1, description="Generated answer summary.")
    claims: Tuple[AnswerClaim, ...] = Field(
        default=(), description="Parsed candidate factual claims."
    )
    limitations: Tuple[str, ...] = Field(
        default=(), description="Model-reported caveats or missing facts."
    )
    sufficient_evidence: bool = Field(
        default=True,
        description="Model self-assessment of whether evidence was sufficient.",
    )


class GroundedAnswer(BaseModel):
    """Governed QA output contract (ARCHITECTURE.md §15.2 & ADR-0020)."""

    model_config = ConfigDict(frozen=True)

    answer: str = Field(description="Final rendered answer or abstention note.")
    claims: Tuple[AnswerClaim, ...] = Field(
        default=(), description="Validated (or annotated) factual claims."
    )
    citations: Tuple[EvidenceEntry, ...] = Field(
        default=(), description="Resolved authorized EvidenceEntry citations."
    )
    limitations: Tuple[str, ...] = Field(
        default=(),
        description="Explicit disclosures, warnings, and caveats.",
    )
    sufficient_evidence: bool = Field(
        default=False,
        description="True iff post-generation validation confirmed support.",
    )
    abstained: bool = Field(
        default=False,
        description="True when the system explicitly abstained from answering.",
    )
    abstention_reason: Optional[str] = Field(
        default=None, description="Explicit rationale when abstained is True."
    )
    qa_mode: QAMode = Field(
        default="standard", description="Executed QA orchestration mode."
    )
    semantic_profile_id: Optional[uuid.UUID] = Field(
        default=None, description="Active semantic profile identifier."
    )
    model_profile_id: Optional[str] = Field(
        default=None, description="Executed approved ModelProfile ID."
    )
    model_profile_version: Optional[str] = Field(
        default=None, description="Executed ModelProfile version."
    )
    validation_report: Optional[Any] = Field(
        default=None,
        description="Post-generation CitationValidationReport when executed.",
    )
    execution_metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Reproducibility, latency, usage, and decomposition trace.",
    )
