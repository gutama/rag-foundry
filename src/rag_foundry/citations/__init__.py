"""Post-generation citation alignment, validation, and sufficiency gating."""

from rag_foundry.citations.aligner import (
    CitationAligner,
    derive_effective_authority,
    resolve_source_span,
)
from rag_foundry.citations.models import (
    CitationIssue,
    CitationValidationIssueCode,
    CitationValidationPolicy,
    CitationValidationReport,
    ClaimAlignmentResult,
    SourceSpan,
    UnsupportedClaimAction,
)
from rag_foundry.citations.sufficiency import SufficiencyGate
from rag_foundry.citations.validator import CitationValidator

__all__ = [
    "CitationAligner",
    "CitationIssue",
    "CitationValidationIssueCode",
    "CitationValidationPolicy",
    "CitationValidationReport",
    "CitationValidator",
    "ClaimAlignmentResult",
    "SourceSpan",
    "SufficiencyGate",
    "UnsupportedClaimAction",
    "derive_effective_authority",
    "resolve_source_span",
]
