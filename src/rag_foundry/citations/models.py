"""Domain models for citation validation, alignment, and sufficiency gates."""

import uuid
from typing import Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from rag_foundry.generation.models import AnswerClaim, ClaimAuthority
from rag_foundry.retrieval.models import BoundingBox

UnsupportedClaimAction = Literal["abstain", "strip_and_warn", "warn"]

CitationValidationIssueCode = Literal[
    "unknown_citation_id",
    "unauthorized_workspace",
    "unauthorized_security_domain",
    "superseded_document_revision",
    "unresolvable_source_span",
    "missing_claim_citation",
    "unsupported_claim",
    "numeric_mismatch",
    "authority_misrepresentation",
    "low_evidence_confidence",
    "extracted_only_disallowed",
    "empty_claims",
]


class CitationValidationPolicy(BaseModel):
    """Configurable fail-closed policy governing ADR-0020 validation."""

    model_config = ConfigDict(frozen=True)

    reject_invalid_citation_ids: bool = Field(
        default=True,
        description="Fail closed when any citation ID is unknown/unauthorized.",
    )
    require_claim_citations: bool = Field(
        default=True,
        description="Require every factual claim to cite >= 1 evidence handle.",
    )
    min_claim_support_score: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Minimum claim-to-passage lexical/phrase alignment score.",
    )
    min_supported_claim_ratio: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Minimum fraction of claims that must pass support checks.",
    )
    min_evidence_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum average/max confidence of cited evidence entries.",
    )
    allow_extracted_only_answers: bool = Field(
        default=True,
        description=(
            "Whether answers backed solely by unapproved extracted assertions "
            "are permitted (with disclosure) or must abstain."
        ),
    )
    unsupported_claim_action: UnsupportedClaimAction = Field(
        default="abstain",
        description=(
            "Action when unsupported claims remain: abstain, strip_and_warn, "
            "or warn."
        ),
    )
    enforce_revision_check: bool = Field(
        default=True,
        description=(
            "Reject citations pointing to superseded document versions."
        ),
    )
    enforce_span_check: bool = Field(
        default=True,
        description="Reject citations lacking resolvable source spans.",
    )
    reject_authority_misrepresentation: bool = Field(
        default=True,
        description=(
            "Flag/reject claims asserting curated authority from "
            "extracted-only candidate evidence."
        ),
    )
    disclose_extracted_knowledge: bool = Field(
        default=True,
        description=(
            "Append an explicit limitation disclosure whenever claims rely on "
            "unapproved extracted candidate assertions."
        ),
    )


class SourceSpan(BaseModel):
    """Resolved source location provenance for a single citation handle."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(description="Citation handle (e.g. 'E1', 'A1').")
    document_version_id: Optional[uuid.UUID] = Field(default=None)
    chunk_id: Optional[uuid.UUID] = Field(default=None)
    assertion_id: Optional[uuid.UUID] = Field(default=None)
    section_path: Tuple[str, ...] = Field(default=())
    page_numbers: Tuple[int, ...] = Field(default=())
    bounding_boxes: Tuple[BoundingBox, ...] = Field(default=())
    resolvable: bool = Field(
        default=True,
        description="True iff the evidence item carries resolvable provenance.",
    )


class CitationIssue(BaseModel):
    """Structured diagnostic emitted during post-generation validation."""

    model_config = ConfigDict(frozen=True)

    code: CitationValidationIssueCode = Field(description="Typed issue code.")
    severity: Literal["error", "warning"] = Field(description="Severity level.")
    message: str = Field(description="Human-readable diagnostic explanation.")
    claim_index: Optional[int] = Field(default=None)
    evidence_id: Optional[str] = Field(default=None)


class ClaimAlignmentResult(BaseModel):
    """Alignment and provenance outcome for one candidate AnswerClaim."""

    model_config = ConfigDict(frozen=True)

    claim_index: int = Field(ge=0)
    claim: AnswerClaim = Field(
        description="Claim updated with derived authority and support_score."
    )
    matched_evidence_ids: Tuple[str, ...] = Field(default=())
    missing_evidence_ids: Tuple[str, ...] = Field(default=())
    resolved_spans: Tuple[SourceSpan, ...] = Field(default=())
    effective_authority: Optional[ClaimAuthority] = Field(default=None)
    support_score: float = Field(default=0.0, ge=0.0, le=1.0)
    numeric_mismatch: bool = Field(default=False)
    supported: bool = Field(default=False)


class CitationValidationReport(BaseModel):
    """Complete post-generation citation validation report (ADR-0020)."""

    model_config = ConfigDict(frozen=True)

    passed: bool = Field(description="True iff zero blocking errors occurred.")
    claim_results: Tuple[ClaimAlignmentResult, ...] = Field(default=())
    issues: Tuple[CitationIssue, ...] = Field(default=())
    invalid_citation_ids: Tuple[str, ...] = Field(default=())
    unauthorized_citation_ids: Tuple[str, ...] = Field(default=())
    superseded_citation_ids: Tuple[str, ...] = Field(default=())
    unresolvable_span_ids: Tuple[str, ...] = Field(default=())
    authority_misrepresentation_indices: Tuple[int, ...] = Field(default=())
    supported_claim_count: int = Field(default=0, ge=0)
    total_claim_count: int = Field(default=0, ge=0)
    supported_claim_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    curated_claim_count: int = Field(default=0, ge=0)
    extracted_claim_count: int = Field(default=0, ge=0)
    document_claim_count: int = Field(default=0, ge=0)
    mixed_claim_count: int = Field(default=0, ge=0)
    effective_answer_authority: Optional[ClaimAuthority] = Field(default=None)
    has_invalid_citations: bool = Field(default=False)
