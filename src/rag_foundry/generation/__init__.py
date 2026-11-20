"""Grounded generation, formatting, context loading, and QA orchestration."""

from rag_foundry.generation.formatter import (
    CURATED_BANNER,
    CURATED_TAG,
    DOCUMENT_BANNER,
    DOCUMENT_TAG,
    EXTRACTED_BANNER,
    EXTRACTED_TAG,
    EvidenceFormatter,
    FormattedEvidenceContext,
)
from rag_foundry.generation.models import (
    AnswerClaim,
    ClaimAuthority,
    EvidenceEntry,
    GroundedAnswer,
    KnowledgeAuthority,
    ParsedAnswerPayload,
    QAMode,
)
from rag_foundry.generation.parser import AnswerParseError, parse_model_answer
from rag_foundry.generation.prompts import (
    build_decomposition_messages,
    build_qa_messages,
)

__all__ = [
    "AnswerClaim",
    "AnswerParseError",
    "CURATED_BANNER",
    "CURATED_TAG",
    "ClaimAuthority",
    "DOCUMENT_BANNER",
    "DOCUMENT_TAG",
    "EXTRACTED_BANNER",
    "EXTRACTED_TAG",
    "EvidenceEntry",
    "EvidenceFormatter",
    "FormattedEvidenceContext",
    "GroundedAnswer",
    "KnowledgeAuthority",
    "ParsedAnswerPayload",
    "QAMode",
    "build_decomposition_messages",
    "build_qa_messages",
    "parse_model_answer",
]
