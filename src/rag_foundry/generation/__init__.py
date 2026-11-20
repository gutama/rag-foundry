"""Grounded generation, formatting, context loading, and QA orchestration."""

from typing import TYPE_CHECKING, Any

from rag_foundry.generation.context import (
    AssertionContextLoader,
    AssertionContextProvider,
    load_chunk_security_domains,
)
from rag_foundry.generation.decomposer import (
    DecompositionResult,
    QueryDecomposer,
    deterministic_split_question,
)
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

if TYPE_CHECKING:
    from rag_foundry.generation.pipeline import (
        ChunkDomainResolver,
        GroundedQAPipeline,
        GroundedQARequest,
    )

_PIPELINE_EXPORTS = frozenset(
    {"ChunkDomainResolver", "GroundedQAPipeline", "GroundedQARequest"}
)


def __getattr__(name: str) -> Any:
    """Lazily resolve orchestrator exports to avoid package-init cycles."""
    if name in _PIPELINE_EXPORTS:
        from rag_foundry.generation import pipeline

        return getattr(pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AnswerClaim",
    "AnswerParseError",
    "AssertionContextLoader",
    "AssertionContextProvider",
    "CURATED_BANNER",
    "CURATED_TAG",
    "ChunkDomainResolver",
    "ClaimAuthority",
    "DOCUMENT_BANNER",
    "DOCUMENT_TAG",
    "DecompositionResult",
    "EXTRACTED_BANNER",
    "EXTRACTED_TAG",
    "EvidenceEntry",
    "EvidenceFormatter",
    "FormattedEvidenceContext",
    "GroundedAnswer",
    "GroundedQAPipeline",
    "GroundedQARequest",
    "KnowledgeAuthority",
    "ParsedAnswerPayload",
    "QAMode",
    "QueryDecomposer",
    "build_decomposition_messages",
    "build_qa_messages",
    "deterministic_split_question",
    "load_chunk_security_domains",
    "parse_model_answer",
]
